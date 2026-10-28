import uuid
import re
from datetime import timedelta
from time import monotonic

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from files.selectors import member_group
from .answer_provider import answer_provider, PermanentAnswerError, TransientAnswerError
from .models import ActiveIndex, AnswerCitation, DocumentChunk, Question
from .search import search_group


def publish_question(question_id):
    try:
        from .tasks import answer_question
        answer_question.delay(question_id)
    except Exception:
        # Durable QUEUED row is recovered by dispatch_ai_questions.
        pass


def queue_question(user, group, text, request_key=None):
    if not settings.AI_QA_ENABLED:
        raise PermanentAnswerError('qa_disabled')
    if settings.AI_APPROVED_GROUP_ID and group.pk != settings.AI_APPROVED_GROUP_ID:
        raise PermanentAnswerError('qa_outside_approved_group')
    if request_key:
        existing = Question.objects.filter(group=group, user=user, request_key=request_key).first()
        if existing:
            if existing.question != text:
                raise PermanentAnswerError('idempotency_conflict')
            return existing, False
    try:
        with transaction.atomic():
            if settings.AI_QA_TOTAL_QUESTION_LIMIT:
                from groups.models import Group
                Group.objects.select_for_update().get(pk=group.pk)
                if Question.objects.filter(group=group, provider_kind=settings.AI_LLM_PROVIDER).count() >= settings.AI_QA_TOTAL_QUESTION_LIMIT:
                    raise PermanentAnswerError('question_limit_reached')
            question = Question.objects.create(group=group, user=user, question=text,
                request_key=request_key, provider_kind=settings.AI_LLM_PROVIDER,
                model=settings.AI_LLM_MODEL if settings.AI_LLM_PROVIDER == 'openai' else 'fake-v1',
                prompt_revision=settings.AI_LLM_PROMPT_REVISION)
            transaction.on_commit(lambda: publish_question(question.pk))
            return question, True
    except IntegrityError:
        if not request_key:
            raise
        existing = Question.objects.get(group=group, user=user, request_key=request_key)
        if existing.question != text:
            raise PermanentAnswerError('idempotency_conflict')
        return existing, False


def claim_question(question_id):
    with transaction.atomic():
        item = Question.objects.select_for_update().get(pk=question_id)
        if settings.AI_APPROVED_GROUP_ID and (item.group_id != settings.AI_APPROVED_GROUP_ID
                or item.provider_kind != settings.AI_LLM_PROVIDER):
            return None
        now = timezone.now()
        if item.status in (Question.COMPLETED, Question.FAILED):
            return None
        if item.status == Question.GENERATING and item.lease_until and item.lease_until > now:
            return None
        max_attempts = 1 if item.provider_kind == 'openai' else settings.AI_QA_MAX_ATTEMPTS
        if item.attempts >= max_attempts:
            item.status = Question.FAILED
            item.error_code = 'worker_timeout'
            item.completed_at = now
            item.save(update_fields=['status', 'error_code', 'completed_at'])
            return None
        item.status = Question.GENERATING
        item.attempts += 1
        item.lease_token = uuid.uuid4().hex
        item.lease_until = now + timedelta(seconds=settings.AI_QA_LEASE_SECONDS)
        item.save(update_fields=['status', 'attempts', 'lease_token', 'lease_until'])
        return item.lease_token


def source_is_current(chunk, user, group_id):
    return ActiveIndex.objects.filter(job=chunk.job, file=chunk.file_version.file,
        file__group_id=group_id, file__deleted_at__isnull=True,
        file__group__members__user=user, job__status='READY').exists()


def validate_answer(payload, evidence):
    if not isinstance(payload, dict) or set(payload) != {'answer', 'answer_status', 'citations'}:
        raise PermanentAnswerError('invalid_answer_format')
    answer, answer_status, citations = payload['answer'], payload['answer_status'], payload['citations']
    if not isinstance(answer, str) or len(answer) > 4000 or answer_status not in ('answered', 'insufficient_evidence') or not isinstance(citations, list):
        raise PermanentAnswerError('invalid_answer_format')
    allowed = {item['chunk_id']: item for item in evidence}
    if answer_status == 'insufficient_evidence':
        if answer or citations:
            raise PermanentAnswerError('invalid_answer_format')
        return []
    if not answer.strip() or not citations or len(citations) > len(allowed):
        raise PermanentAnswerError('invalid_answer_format')
    validated, seen = [], set()
    for citation in citations:
        if not isinstance(citation, dict) or set(citation) != {'chunk_id', 'quote'}:
            raise PermanentAnswerError('invalid_citation')
        chunk_id, quote = citation['chunk_id'], citation['quote']
        if type(chunk_id) is not int or chunk_id not in allowed or chunk_id in seen or not isinstance(quote, str) or not quote.strip() or len(quote) > 500:
            raise PermanentAnswerError('invalid_citation')
        source = allowed[chunk_id]['content']
        if quote not in source:
            # Recover only spacing differences; store the actual contiguous source text.
            requested = [match.group() for match in re.finditer(r'\S+', quote)]
            source_words = list(re.finditer(r'\S+', source))
            quote = next((source[words[0].start():words[-1].end()]
                for offset in range(len(source_words) - len(requested) + 1)
                for words in [source_words[offset:offset + len(requested)]]
                if [word.group() for word in words] == requested
                and words[-1].end() - words[0].start() <= 500), None)
            if quote is None:
                raise PermanentAnswerError('invalid_citation')
        validated.append((chunk_id, quote))
        seen.add(chunk_id)
    if not any(answer.strip() in quote for _, quote in validated):
        raise PermanentAnswerError('answer_not_in_citation')
    return validated


def finish_question_failure(question_id, token, code, transient=False):
    with transaction.atomic():
        item = Question.objects.select_for_update().get(pk=question_id)
        if item.status != Question.GENERATING or item.lease_token != token:
            return False
        retry = transient and item.provider_kind == 'fake' and item.attempts < settings.AI_QA_MAX_ATTEMPTS
        item.status = Question.QUEUED if retry else Question.FAILED
        item.error_code = code
        item.lease_token = ''
        item.lease_until = None
        item.completed_at = None if retry else timezone.now()
        item.save(update_fields=['status', 'error_code', 'lease_token', 'lease_until', 'completed_at'])
        return retry


def process_question(question_id):
    token = claim_question(question_id)
    if not token:
        return
    started = monotonic()
    try:
        item = Question.objects.select_related('user').get(pk=question_id)
        if item.prompt_revision != settings.AI_LLM_PROMPT_REVISION:
            raise PermanentAnswerError('configuration_changed')
        member_group(item.user, item.group_id)
        if not ActiveIndex.objects.filter(file__group_id=item.group_id, file__deleted_at__isnull=True, job__status='READY').exists():
            result, input_tokens, output_tokens = ({'answer': '', 'answer_status': 'insufficient_evidence', 'citations': []}, 0, 0)
            evidence = []
        else:
            found = search_group(item.user, item.group_id, item.question, limit=5)
            evidence, used = [], 0
            for hit in found:
                content = hit['content']
                if used + len(content) > settings.AI_QA_MAX_CONTEXT_CHARS:
                    continue
                chunk = DocumentChunk.objects.select_related('file_version__file').get(pk=hit['chunk_id'])
                if not source_is_current(chunk, item.user, item.group_id):
                    continue
                evidence.append({'chunk_id': chunk.id, 'content': content})
                used += len(content)
            if evidence:
                result, input_tokens, output_tokens = answer_provider(item.provider_kind).generate(item.question, evidence, model=item.model)
            else:
                result, input_tokens, output_tokens = ({'answer': '', 'answer_status': 'insufficient_evidence', 'citations': []}, 0, 0)
        citations = validate_answer(result, evidence)
        with transaction.atomic():
            locked = Question.objects.select_for_update().get(pk=question_id)
            if locked.status != Question.GENERATING or locked.lease_token != token:
                return
            member_group(locked.user, locked.group_id)
            chunks = {chunk.id: chunk for chunk in DocumentChunk.objects.select_related('file_version__file').filter(pk__in=[entry['chunk_id'] for entry in evidence])}
            from files.models import File
            list(File.objects.select_for_update().filter(pk__in={chunk.file_version.file_id for chunk in chunks.values()}).order_by('pk'))
            if len(chunks) != len(evidence) or any(not source_is_current(chunk, locked.user, locked.group_id) for chunk in chunks.values()):
                raise PermanentAnswerError('source_changed')
            AnswerCitation.objects.filter(question=locked).delete()
            for ordinal, (chunk_id, quote) in enumerate(citations):
                AnswerCitation.objects.create(question=locked, chunk=chunks[chunk_id],
                    file_version=chunks[chunk_id].file_version, quote=quote, ordinal=ordinal)
            locked.answer = result['answer']
            locked.answer_status = result['answer_status']
            locked.status = Question.COMPLETED
            locked.error_code = ''
            locked.input_tokens = input_tokens
            locked.output_tokens = output_tokens
            locked.duration_ms = int((monotonic() - started) * 1000)
            locked.completed_at = timezone.now()
            locked.lease_token = ''
            locked.lease_until = None
            locked.save(update_fields=['answer', 'answer_status', 'status', 'error_code', 'input_tokens',
                'output_tokens', 'duration_ms', 'completed_at', 'lease_token', 'lease_until'])
    except PermanentAnswerError as exc:
        finish_question_failure(question_id, token, str(exc))
    except Http404:
        finish_question_failure(question_id, token, 'access_revoked')
    except Exception:
        retry = finish_question_failure(question_id, token, 'temporary_failure', transient=True)
        if retry:
            try:
                from .tasks import answer_question
                answer_question.apply_async(args=[question_id], countdown=5)
            except Exception:
                pass
