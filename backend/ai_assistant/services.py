import hashlib
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .chunking import split_text
from .models import AIProcessingJob, ActiveIndex, DocumentChunk
from .providers import provider, PermanentEmbeddingError, TransientEmbeddingError
from . import vector_store


def configuration():
    if settings.AI_CHUNK_CHARS > 2000 or settings.AI_CHUNK_CHARS < 1 or settings.AI_CHUNK_OVERLAP_CHARS >= settings.AI_CHUNK_CHARS:
        raise ValueError('Invalid AI chunk configuration')
    identity = '|'.join(map(str, (settings.AI_EMBEDDING_PROVIDER, settings.AI_EMBEDDING_MODEL,
        settings.AI_EMBEDDING_DIMENSION, settings.AI_SPLIT_REVISION, settings.AI_CHUNK_CHARS,
        settings.AI_CHUNK_OVERLAP_CHARS, settings.AI_INDEX_REVISION)))
    key = hashlib.sha256(identity.encode()).hexdigest()
    collection = re.sub(r'[^a-zA-Z0-9_-]', '_',
        f"bees_{settings.AI_EMBEDDING_PROVIDER}_{settings.AI_EMBEDDING_MODEL}_{settings.AI_EMBEDDING_DIMENSION}_{settings.AI_INDEX_REVISION}")[:90]
    return key, collection


def publish_job(job_id):
    from .tasks import process_document
    try:
        process_document.delay(job_id)
    except Exception:
        # The durable PENDING row is recovered by dispatch_ai_jobs.
        pass


def queue_version(version):
    if not settings.AI_INDEX_ENABLED:
        return None
    key, collection = configuration()
    job, _ = AIProcessingJob.objects.get_or_create(file_version=version, config_key=key, defaults={
        'content_hash': version.sha256 or '', 'split_revision': settings.AI_SPLIT_REVISION,
        'embedding_provider': settings.AI_EMBEDDING_PROVIDER, 'embedding_model': settings.AI_EMBEDDING_MODEL,
        'embedding_dimension': settings.AI_EMBEDDING_DIMENSION, 'index_revision': settings.AI_INDEX_REVISION,
        'collection_name': collection,
    })
    if job.status == AIProcessingJob.PENDING:
        transaction.on_commit(lambda: publish_job(job.pk))
    return job


def claim_job(job_id):
    with transaction.atomic():
        job = AIProcessingJob.objects.select_for_update().select_related('file_version__file').get(pk=job_id)
        if settings.AI_APPROVED_GROUP_ID and (job.file_version.file.group_id != settings.AI_APPROVED_GROUP_ID
                or job.embedding_provider != settings.AI_EMBEDDING_PROVIDER
                or job.index_revision != settings.AI_INDEX_REVISION
                or (settings.AI_INDEX_CURRENT_ONLY and
                    job.file_version.version_number != job.file_version.file.current_version_number)):
            return None
        now = timezone.now()
        if job.status == AIProcessingJob.READY or job.status == AIProcessingJob.CANCELED:
            return None
        if job.status == AIProcessingJob.RUNNING and job.lease_until and job.lease_until > now:
            return None
        if job.status == AIProcessingJob.FAILED:
            return None
        if job.attempts >= settings.AI_MAX_ATTEMPTS + job.manual_retries:
            job.status = AIProcessingJob.FAILED
            job.error_code = 'worker_timeout'
            job.completed_at = now
            job.lease_until = None
            job.lease_token = ''
            job.save(update_fields=['status', 'error_code', 'completed_at', 'lease_until', 'lease_token'])
            return None
        if job.file_version.file.deleted_at:
            job.status = AIProcessingJob.CANCELED
            job.completed_at = now
            job.save(update_fields=['status', 'completed_at'])
            return None
        job.status = AIProcessingJob.RUNNING
        job.attempts += 1
        job.started_at = now
        job.lease_until = now + timedelta(seconds=settings.AI_LEASE_SECONDS)
        job.lease_token = uuid.uuid4().hex
        job.error_code = ''
        job.save(update_fields=['status', 'attempts', 'started_at', 'lease_until', 'lease_token', 'error_code'])
        return job.pk, job.lease_token


def finish_failure(job_id, token, code, transient):
    with transaction.atomic():
        job = AIProcessingJob.objects.select_for_update().get(pk=job_id)
        if job.lease_token != token or job.status != AIProcessingJob.RUNNING:
            return False
        retry = transient and job.attempts < settings.AI_MAX_ATTEMPTS
        job.status = AIProcessingJob.PENDING if retry else AIProcessingJob.FAILED
        job.error_code = code
        job.lease_until = None
        job.lease_token = ''
        job.completed_at = None if retry else timezone.now()
        job.save(update_fields=['status', 'error_code', 'lease_until', 'lease_token', 'completed_at'])
        return retry


def process_job(job_id):
    claim = claim_job(job_id)
    if not claim:
        return
    _, token = claim
    try:
        job = AIProcessingJob.objects.select_related('file_version__file').get(pk=job_id)
        version = job.file_version
        raw = version.uploaded_file.read(settings.AI_MAX_DOCUMENT_CHARS * 4 + 1)
        text = raw.decode('utf-8', errors='strict')
        if not text.strip() or len(text) > settings.AI_MAX_DOCUMENT_CHARS or hashlib.sha256(raw).hexdigest() != job.content_hash:
            raise PermanentEmbeddingError('invalid_source')
        pieces = list(split_text(text, settings.AI_CHUNK_CHARS, settings.AI_CHUNK_OVERLAP_CHARS))
        if not pieces:
            raise PermanentEmbeddingError('empty_source')
        with transaction.atomic():
            for piece in pieces:
                point_id = uuid.uuid5(uuid.NAMESPACE_URL, f'bees:{job.pk}:{piece["ordinal"]}')
                DocumentChunk.objects.update_or_create(job=job, ordinal=piece['ordinal'], defaults={
                    'file_version': version, 'content': piece['content'],
                    'content_hash': hashlib.sha256(piece['content'].encode()).hexdigest(),
                    'heading': piece['heading'], 'paragraph_number': piece['paragraph_number'],
                    'char_start': piece['char_start'], 'char_end': piece['char_end'], 'point_id': point_id,
                })
        chunks = list(job.chunks.order_by('ordinal'))
        embedder = provider(job.embedding_provider)
        embeddings = embedder.embed([chunk.content for chunk in chunks], job.embedding_dimension, job.embedding_model)
        if len(embeddings) != len(chunks) or any(len(vector) != job.embedding_dimension for vector in embeddings):
            raise PermanentEmbeddingError('invalid_vector_dimensions')
        store = vector_store.client()
        vector_store.ensure_collection(store, job)
        vector_store.upsert_chunks(store, job, chunks, embeddings)
        with transaction.atomic():
            locked = AIProcessingJob.objects.select_for_update().get(pk=job_id)
            file = version.file.__class__.objects.select_for_update().get(pk=version.file_id)
            if locked.lease_token != token or locked.status != AIProcessingJob.RUNNING:
                return
            if file.deleted_at:
                locked.status = AIProcessingJob.CANCELED
            else:
                locked.status = AIProcessingJob.READY
                if file.current_version_number == version.version_number:
                    ActiveIndex.objects.update_or_create(file=file, defaults={'job': locked})
            locked.completed_at = timezone.now()
            locked.embedding_tokens = getattr(embedder, 'usage_tokens', 0)
            locked.lease_until = None
            locked.lease_token = ''
            locked.save(update_fields=['status', 'completed_at', 'lease_until', 'lease_token', 'embedding_tokens'])
    except (UnicodeError, PermanentEmbeddingError) as exc:
        finish_failure(job_id, token, str(exc) if isinstance(exc, PermanentEmbeddingError) else 'invalid_utf8', False)
    except Exception as exc:
        retry = finish_failure(job_id, token, 'temporary_failure', True)
        if retry:
            from .tasks import process_document
            try:
                process_document.apply_async(args=[job_id], countdown=10)
            except Exception:
                pass
