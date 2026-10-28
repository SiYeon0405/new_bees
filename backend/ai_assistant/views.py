from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from config.authentication import BrowserAPIAuthentication
from files.selectors import member_group, group_file, file_version
from .models import AIProcessingJob, ActiveIndex, Question, QuestionFeedback
from .services import configuration, publish_job
from .answers import queue_question, source_is_current
from .answer_provider import PermanentAnswerError
from django.utils import timezone


def status_data(document, version):
    active = ActiveIndex.objects.select_related('job__file_version').filter(file=document).first()
    active_number = active.job.file_version.version_number if active else None
    if not settings.AI_INDEX_ENABLED:
        return {'status': 'DISABLED', 'job_id': None, 'searchable_version_number': active_number}
    key, _ = configuration()
    job = AIProcessingJob.objects.filter(file_version=version, config_key=key).first()
    return {'status': job.status if job else 'PENDING', 'job_id': job.id if job else None,
            'attempts': job.attempts if job else 0, 'error_code': job.error_code if job else '',
            'searchable_version_number': active_number,
            'provider': job.embedding_provider if job else settings.AI_EMBEDDING_PROVIDER}


class VersionIndexView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id, file_id, version_id):
        group = member_group(request.user, group_id)
        document = group_file(group, file_id)
        version = file_version(document, version_id)
        return Response(status_data(document, version))


class VersionRetryView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id, file_id, version_id):
        group = member_group(request.user, group_id)
        document = group_file(group, file_id)
        version = file_version(document, version_id)
        if request.user.id not in (document.created_by_id, group.owner_id):
            return Response({'detail': 'Retry requires document uploader or group owner.'}, status=403)
        if not settings.AI_INDEX_ENABLED or not settings.AI_MANUAL_RETRY_ENABLED:
            return Response({'detail': 'Indexing is disabled.'}, status=409)
        key, _ = configuration()
        with transaction.atomic():
            job = get_object_or_404(AIProcessingJob.objects.select_for_update(), file_version=version, config_key=key)
            if job.status != AIProcessingJob.FAILED or job.error_code != 'temporary_failure' or job.manual_retries >= 1:
                return Response({'detail': 'Retry is not available.'}, status=409)
            job.manual_retries = 1
            job.status = AIProcessingJob.PENDING
            job.error_code = ''
            job.save(update_fields=['manual_retries', 'status', 'error_code'])
            transaction.on_commit(lambda: publish_job(job.id))
        return Response(status_data(document, version), status=202)


def question_data(item):
    data = {'id': item.id, 'status': item.status, 'answer_status': item.answer_status or None,
            'answer': None, 'citations': [], 'error_code': item.error_code,
            'model': item.model, 'prompt_revision': item.prompt_revision,
            'input_tokens': item.input_tokens, 'output_tokens': item.output_tokens,
            'duration_ms': item.duration_ms}
    if item.status != Question.COMPLETED:
        return data
    citations = list(item.citations.select_related('chunk__file_version__file', 'file_version').order_by('ordinal'))
    if any(not source_is_current(citation.chunk, item.user, item.group_id)
           or citation.file_version_id != citation.chunk.file_version_id for citation in citations):
        data.update(status='SOURCE_UNAVAILABLE', answer_status=None, error_code='source_unavailable')
        return data
    data['answer'] = item.answer
    data['citations'] = [{'chunk_id': citation.chunk_id, 'file_id': citation.file_version.file_id,
        'version_id': citation.file_version_id, 'version_number': citation.file_version.version_number,
        'document_name': citation.file_version.file.name, 'quote': citation.quote,
        'download_url': f'/api/groups/{item.group_id}/files/{citation.file_version.file_id}/versions/{citation.file_version_id}/download/'}
        for citation in citations]
    return data


class QuestionCreateView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):
        group = member_group(request.user, group_id)
        text = request.data.get('question')
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            return Response({'question': 'Question must contain 1–1000 characters.'}, status=400)
        request_key = request.headers.get('Idempotency-Key')
        if request_key is not None and (not request_key.isascii() or len(request_key) > 80 or not request_key.strip()):
            return Response({'detail': 'Invalid Idempotency-Key.'}, status=400)
        if request_key:
            existing = Question.objects.filter(user=request.user, group=group, request_key=request_key).first()
            if existing:
                if existing.question != text.strip():
                    return Response({'detail': 'Idempotency-Key was used for a different question.'}, status=409)
                return Response({'question_id': existing.id, 'job_id': existing.id, 'status': existing.status}, status=202)
        if Question.objects.filter(user=request.user, group=group, created_at__date=timezone.now().date()).count() >= 20:
            return Response({'detail': 'Daily question limit reached.'}, status=429)
        try:
            item, _ = queue_question(request.user, group, text.strip(), request_key)
        except PermanentAnswerError as exc:
            if str(exc) == 'idempotency_conflict':
                return Response({'detail': 'Idempotency-Key was used for a different question.'}, status=409)
            if str(exc) == 'question_limit_reached':
                return Response({'detail': 'Approved question limit reached.'}, status=429)
            return Response({'detail': 'Question answering is unavailable.'}, status=503)
        return Response({'question_id': item.id, 'job_id': item.id, 'status': item.status}, status=202)


class QuestionDetailView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id, question_id):
        group = member_group(request.user, group_id)
        item = get_object_or_404(Question, pk=question_id, group=group, user=request.user)
        return Response(question_data(item))


class QuestionFeedbackView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id, question_id):
        group = member_group(request.user, group_id)
        item = get_object_or_404(Question, pk=question_id, group=group, user=request.user, status=Question.COMPLETED)
        if question_data(item)['status'] == 'SOURCE_UNAVAILABLE':
            return Response({'detail': 'Source is no longer available.'}, status=409)
        if type(request.data.get('rating')) is not int or request.data['rating'] not in (-1, 1):
            return Response({'rating': 'Use -1 or 1.'}, status=400)
        feedback, created = QuestionFeedback.objects.update_or_create(question=item,
            defaults={'user': request.user, 'rating': request.data['rating']})
        return Response({'rating': feedback.rating}, status=201 if created else 200)
