import hashlib
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

from groups.models import Group, GroupMember
from users.models import User
from files.services import create_version, delete_file
from .chunking import split_text
from .models import AIProcessingJob, ActiveIndex, DocumentChunk
from .services import process_job, queue_version
from .search import search_group
from .providers import OpenAIEmbeddings, PermanentEmbeddingError, reserve_real_evaluation_call
from .management.commands.evaluate_search import load_fixture
from pathlib import Path
from types import SimpleNamespace


AI_TEST = dict(AI_INDEX_ENABLED=True, AI_EMBEDDING_PROVIDER='fake', AI_EMBEDDING_MODEL='test-fake',
               AI_EMBEDDING_DIMENSION=16, AI_INDEX_REVISION='test-v1', AI_CHUNK_CHARS=20,
               AI_CHUNK_OVERLAP_CHARS=4, AI_MAX_DOCUMENT_CHARS=2000)


class ProviderAndFixtureTests(SimpleTestCase):
    def test_fixture_references_and_bounded_size(self):
        fixture = Path('/app/search_eval_fixture.json')
        if not fixture.exists():
            fixture = Path(__file__).resolve().parents[2] / 'docs' / 'search_eval_fixture.json'
        payload, size = load_fixture(fixture)
        self.assertEqual((len(payload['documents']), len(payload['questions'])), (6, 15))
        self.assertLessEqual(size, 12000)

    def test_real_evaluation_rejects_unapproved_content_before_network(self):
        mocked_settings = SimpleNamespace(AI_EMBEDDING_MODEL='text-embedding-3-small',
            AI_EMBEDDING_DIMENSION=512, AI_INDEX_REVISION='openai-eval-v1',
            DATABASES={'default': {'NAME': 'bees_openai_eval'}})
        with patch.dict('os.environ', {'AI_REAL_EVAL_ENABLED': 'true'}), patch('ai_assistant.providers.settings', mocked_settings):
            with self.assertRaisesRegex(PermanentEmbeddingError, 'evaluation_input_not_approved'):
                reserve_real_evaluation_call(['private document outside fixture'])

    @override_settings(OPENAI_API_KEY='test-placeholder', AI_MAX_EMBEDDING_INPUT_BYTES=100)
    def test_provider_batch_response_and_usage_without_network(self):
        response = SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[0.0] * 3),
                                         SimpleNamespace(index=0, embedding=[1.0] * 3)],
                                   usage=SimpleNamespace(total_tokens=7))
        with patch('openai.OpenAI') as factory:
            factory.return_value.embeddings.create.return_value = response
            embedder = OpenAIEmbeddings()
            vectors = embedder.embed(['first', 'second'], 3, 'text-embedding-3-small')
        self.assertEqual(vectors[0], [1.0] * 3)
        self.assertEqual(embedder.usage_tokens, 7)
        factory.assert_called_once_with(api_key='test-placeholder', timeout=30, max_retries=0)
        with self.assertRaises(PermanentEmbeddingError):
            OpenAIEmbeddings().embed(['x' * 101], 3)


@override_settings(**AI_TEST)
class IndexTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        media_setting = override_settings(MEDIA_ROOT=self.media.name)
        media_setting.enable()
        self.addCleanup(media_setting.disable)
        self.user = User.objects.create_user(email='index@test.local', nickname='index', password='Strong-pass-789!')
        self.other = User.objects.create_user(email='otherindex@test.local', nickname='other', password='Strong-pass-789!')
        self.group = Group.objects.create(name='index', owner=self.user)
        GroupMember.objects.create(group=self.group, user=self.user, role='owner')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make_version(self, text=b'# Heading\n\nFirst paragraph.\n\nSecond paragraph.'):
        document, version = create_version(self.group, self.user, SimpleUploadedFile('notes.md', text))
        return document, version, AIProcessingJob.objects.get(file_version=version)

    def test_chunk_offsets_and_overlap(self):
        text = '# Topic\n\nFirst paragraph.\n\nSecond paragraph that is long.'
        chunks = list(split_text(text, 24, 4))
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(text[chunk['char_start']:chunk['char_end']], chunk['content'])
            self.assertLessEqual(len(chunk['content']), 24)
        self.assertEqual(chunks[0]['heading'], 'Topic')

    def test_upload_commit_publish_and_rollback(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            document, version, job = self.make_version()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(job.status, 'PENDING')
        with patch('ai_assistant.services.publish_job') as publish:
            callbacks[0]()
            publish.assert_called_once_with(job.id)
        self.assertEqual(queue_version(version).id, job.id)
        self.assertEqual(AIProcessingJob.objects.filter(file_version=version).count(), 1)
        from django.db import transaction
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            try:
                with transaction.atomic():
                    self.make_version(b'rollback')
                    raise RuntimeError('rollback')
            except RuntimeError:
                pass
        self.assertEqual(callbacks, [])

    def test_process_idempotent_partial_failure_and_deleted_file(self):
        document, version, job = self.make_version()
        with patch('ai_assistant.services.vector_store.client') as store_client:
            store = store_client.return_value
            with patch('ai_assistant.services.vector_store.ensure_collection'), patch('ai_assistant.services.vector_store.upsert_chunks') as upsert:
                process_job(job.id)
                job.refresh_from_db()
                self.assertEqual(job.status, 'READY')
                self.assertEqual(ActiveIndex.objects.get(file=document).job_id, job.id)
                count = DocumentChunk.objects.filter(job=job).count()
                self.assertGreater(count, 0)
                process_job(job.id)
                self.assertEqual(DocumentChunk.objects.filter(job=job).count(), count)
                self.assertEqual(upsert.call_count, 1)
        delete_file(document)
        self.assertFalse(ActiveIndex.objects.filter(file=document).exists())

    def test_older_job_finishing_late_does_not_replace_newer_index(self):
        document, first, old_job = self.make_version(b'first document text')
        _, second = create_version(self.group, self.user, SimpleUploadedFile('notes.md', b'second document text'), document)
        new_job = AIProcessingJob.objects.get(file_version=second)
        with patch('ai_assistant.services.vector_store.client'), patch('ai_assistant.services.vector_store.ensure_collection'), patch('ai_assistant.services.vector_store.upsert_chunks'):
            process_job(new_job.id)
            process_job(old_job.id)
        self.assertEqual(ActiveIndex.objects.get(file=document).job_id, new_job.id)

    def test_partial_vector_failure_never_activates(self):
        document, _, job = self.make_version()
        with patch('ai_assistant.services.vector_store.client'), patch('ai_assistant.services.vector_store.ensure_collection'), patch('ai_assistant.services.vector_store.upsert_chunks', side_effect=OSError('partial')):
            with patch('ai_assistant.tasks.process_document.apply_async'):
                process_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'PENDING')
        self.assertFalse(ActiveIndex.objects.filter(file=document).exists())

    def test_delete_during_upsert_cancels_activation(self):
        document, _, job = self.make_version()
        with patch('ai_assistant.services.vector_store.client'), patch('ai_assistant.services.vector_store.ensure_collection'):
            with patch('ai_assistant.services.vector_store.upsert_chunks', side_effect=lambda *args: delete_file(document)):
                process_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'CANCELED')
        self.assertFalse(ActiveIndex.objects.filter(file=document).exists())

    def test_expired_lease_exhaustion_marks_failed(self):
        from django.utils import timezone
        from datetime import timedelta
        from .services import claim_job
        _, _, job = self.make_version()
        job.status = 'RUNNING'
        job.attempts = 3
        job.lease_until = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=['status', 'attempts', 'lease_until'])
        self.assertIsNone(claim_job(job.id))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code), ('FAILED', 'worker_timeout'))

    def test_transient_and_permanent_failure(self):
        _, _, job = self.make_version()
        with patch('ai_assistant.services.provider') as get_provider, patch('ai_assistant.tasks.process_document.apply_async'):
            from .providers import TransientEmbeddingError
            get_provider.return_value.embed.side_effect = TransientEmbeddingError('temporary')
            process_job(job.id)
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts), ('PENDING', 1))
        with patch('ai_assistant.services.provider') as get_provider, patch('ai_assistant.tasks.process_document.apply_async'):
            get_provider.return_value.embed.side_effect = TransientEmbeddingError('temporary')
            process_job(job.id)
            process_job(job.id)
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts), ('FAILED', 3))
        _, _, bad = self.make_version(b'valid source')
        bad.content_hash = '0' * 64
        bad.save(update_fields=['content_hash'])
        process_job(bad.id)
        bad.refresh_from_db()
        self.assertEqual(bad.error_code, 'invalid_source')

    def test_status_and_retry_permissions(self):
        document, version, job = self.make_version()
        base = f'/api/groups/{self.group.id}/files/{document.id}/versions/{version.id}/index/'
        self.assertEqual(self.client.get(base).data['status'], 'PENDING')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(base).status_code, 404)
        self.assertEqual(self.client.post(base + 'retry/').status_code, 404)
        self.client.force_authenticate(self.user)
        job.status = 'FAILED'
        job.error_code = 'temporary_failure'
        job.attempts = 3
        job.save(update_fields=['status', 'error_code', 'attempts'])
        with self.captureOnCommitCallbacks(execute=False):
            self.assertEqual(self.client.post(base + 'retry/').status_code, 202)
        self.assertEqual(self.client.post(base + 'retry/').status_code, 409)


@override_settings(**AI_TEST)
class ConcurrentClaimTests(TransactionTestCase):
    def test_two_mysql_connections_claim_once(self):
        if connection.vendor != 'mysql':
            self.skipTest('MySQL row locking required')
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media, AI_INDEX_ENABLED=False):
                user = User.objects.create_user(email='claim@test.local', nickname='claim', password='Strong-pass-789!')
                group = Group.objects.create(name='claim', owner=user)
                document, version = create_version(group, user, SimpleUploadedFile('claim.md', b'claim text'))
            job = AIProcessingJob.objects.create(file_version=version, config_key='claim-test',
                content_hash=hashlib.sha256(b'claim text').hexdigest(), split_revision='test',
                embedding_provider='fake', embedding_model='test', embedding_dimension=16,
                index_revision='test', collection_name='claim_test')
            from .services import claim_job
            def worker(_):
                close_old_connections()
                try:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT CONNECTION_ID()')
                        identity = cursor.fetchone()[0]
                    return identity, claim_job(job.id)
                finally:
                    close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(worker, (1, 2)))
            self.assertEqual(len({row[0] for row in claims}), 2)
            self.assertEqual(sum(row[1] is not None for row in claims), 1)
            job.refresh_from_db()
            self.assertEqual((job.status, job.attempts), ('RUNNING', 1))
