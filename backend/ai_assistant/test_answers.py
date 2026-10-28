import hashlib
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from files.services import create_version, delete_file
from groups.models import Group, GroupMember
from users.models import User
from .answer_provider import FakeAnswerProvider, OpenAIAnswerProvider, PermanentAnswerError, TransientAnswerError
from .answers import process_question, validate_answer
from .models import ActiveIndex, AIProcessingJob, AnswerCitation, DocumentChunk, Question
from .llm_evaluation_budget import EvaluationBudgetError, reserve_next, dollars


QA_TEST = dict(AI_QA_ENABLED=True, AI_LLM_PROVIDER='fake', AI_EMBEDDING_PROVIDER='fake',
               AI_QA_MAX_ATTEMPTS=2, AI_QA_MAX_CONTEXT_CHARS=6000,
               AI_LLM_PROMPT_REVISION='test-v1')


class CitationSpacingTests(SimpleTestCase):
    def test_fake_answer_and_spacing_only_quote_recovery(self):
        evidence = [{'chunk_id': 5, 'content': '인증 정책: 세션과 CSRF를 사용합니다.\n그룹 멤버만 접근합니다.'}]
        answer, _, _ = FakeAnswerProvider().generate('그룹 멤버 접근 정책은?', evidence)
        self.assertEqual(validate_answer(answer, evidence)[0][0], 5)
        payload = {'answer': '그룹 멤버만 접근합니다.', 'answer_status': 'answered',
                   'citations': [{'chunk_id': 5, 'quote': '그룹   멤버만 접근합니다.'}]}
        self.assertEqual(validate_answer(payload, evidence), [(5, '그룹 멤버만 접근합니다.')])

    def test_forged_text_and_chunk_id_still_fail(self):
        evidence = [{'chunk_id': 5, 'content': '그룹 멤버만 접근합니다.'}]
        for chunk_id, quote in ((5, '모든 사용자가 접근합니다.'), (6, '그룹 멤버만 접근합니다.')):
            with self.assertRaisesRegex(PermanentAnswerError, 'invalid_citation'):
                validate_answer({'answer': quote, 'answer_status': 'answered',
                                 'citations': [{'chunk_id': chunk_id, 'quote': quote}]}, evidence)


class ExternalProviderGateTests(SimpleTestCase):
    @override_settings(AI_LLM_EXTERNAL_ENABLED=False, OPENAI_API_KEY='placeholder')
    def test_external_llm_requires_separate_enablement(self):
        with self.assertRaisesRegex(PermanentAnswerError, 'provider_not_enabled'):
            OpenAIAnswerProvider().generate('question', [{'chunk_id': 1, 'content': 'synthetic'}])

    @override_settings(AI_LLM_EXTERNAL_ENABLED=True, AI_LLM_EVAL_MODE=True,
                       OPENAI_API_KEY='placeholder', AI_LLM_MAX_OUTPUT_TOKENS=200)
    def test_real_evaluation_rejects_missing_exact_input_count_before_api(self):
        with patch('openai.OpenAI') as sdk:
            with self.assertRaisesRegex(PermanentAnswerError, 'trusted_input_token_count_required'):
                OpenAIAnswerProvider().generate('synthetic question',
                    [{'chunk_id': 1, 'content': 'synthetic evidence'}])
            sdk.assert_not_called()

    def test_maximum_next_cost_is_reserved_before_call(self):
        class MemoryLedger:
            requests = 0
            reserved = 0
            def eval(self, script, keys, *args):
                amount = args[-1]
                if self.requests + 1 > 6 or self.reserved + amount > 5_000_000:
                    return 0
                self.requests += 1
                self.reserved += amount
                return 1
        ledger = MemoryLedger()
        for _ in range(5):
            reserve_next(ledger, exact_input_tokens=5000, payload_bytes=1200)
        with self.assertRaisesRegex(EvaluationBudgetError, 'approved_budget_exceeded'):
            reserve_next(ledger, exact_input_tokens=5000, payload_bytes=1200)
        self.assertEqual(ledger.requests, 5)
        self.assertLess(dollars(ledger.reserved), dollars(5_000_000))


@override_settings(**QA_TEST)
class AnswerTests(TestCase):
    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        setting = override_settings(MEDIA_ROOT=media.name, AI_INDEX_ENABLED=False)
        setting.enable()
        self.addCleanup(setting.disable)
        self.user = User.objects.create_user(email='ask@example.invalid', nickname='ask', password='Strong-pass-789!')
        self.other = User.objects.create_user(email='otherask@example.invalid', nickname='other', password='Strong-pass-789!')
        self.group = Group.objects.create(name='alpha', owner=self.user)
        GroupMember.objects.create(group=self.group, user=self.user, role='owner')
        GroupMember.objects.create(group=self.group, user=self.other, role='member')
        self.foreign = Group.objects.create(name='beta', owner=self.other)
        GroupMember.objects.create(group=self.foreign, user=self.other, role='owner')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.base = f'/api/groups/{self.group.id}/ai/questions/'

    def make_source(self, text='초대 코드는 24시간 뒤 만료한다.\n추가 근거 내용입니다.'):
        document, version = create_version(self.group, self.user,
            SimpleUploadedFile('policy.md', text.encode('utf-8')))
        job = AIProcessingJob.objects.create(file_version=version, config_key=uuid.uuid4().hex,
            status='READY', content_hash=hashlib.sha256(text.encode()).hexdigest(),
            split_revision='test', embedding_provider='fake', embedding_model='fake',
            embedding_dimension=16, index_revision='qa-test', collection_name='qa_test')
        chunk = DocumentChunk.objects.create(job=job, file_version=version, ordinal=0,
            content=text, content_hash=hashlib.sha256(text.encode()).hexdigest(),
            paragraph_number=1, char_start=0, char_end=len(text), point_id=uuid.uuid4())
        ActiveIndex.objects.create(file=document, job=job)
        return document, version, chunk

    def make_question(self, text='invite code 만료 시간은?'):
        return Question.objects.create(group=self.group, user=self.user, question=text,
            model='fake-v1', prompt_revision='test-v1')

    def test_fake_provider_uses_second_candidate_and_abstains(self):
        provider = FakeAnswerProvider()
        evidence = [{'chunk_id': 1, 'content': '로그인 토큰은 1일 뒤 만료한다.'},
                    {'chunk_id': 2, 'content': '초대 코드는 24시간 뒤 만료한다.'}]
        result, _, _ = provider.generate('invite code 만료 시간은?', evidence)
        self.assertEqual(result['citations'][0]['chunk_id'], 2)
        result, _, _ = provider.generate('베타 배포 승인 담당자는 누구?', evidence)
        self.assertEqual(result['answer_status'], 'insufficient_evidence')

    def test_api_queue_idempotency_permissions_feedback_and_completion(self):
        document, version, chunk = self.make_source()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.post(self.base, {'question': 'invite code 만료 시간은?'}, format='json',
                HTTP_IDEMPOTENCY_KEY='request-1')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(callbacks), 1)
        question_id = response.data['question_id']
        repeated = self.client.post(self.base, {'question': 'invite code 만료 시간은?'}, format='json',
            HTTP_IDEMPOTENCY_KEY='request-1')
        self.assertEqual(repeated.data['question_id'], question_id)
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(self.client.post(self.base, {'question': '다른 질문'}, format='json',
            HTTP_IDEMPOTENCY_KEY='request-1').status_code, 409)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.base + f'{question_id}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/groups/{self.foreign.id}/ai/questions/{question_id}/').status_code, 404)
        self.client.force_authenticate(self.user)
        with patch('ai_assistant.answers.search_group', return_value=[
            {'chunk_id': chunk.id, 'content': chunk.content, 'file_id': document.id, 'version_id': version.id}]):
            process_question(question_id)
        data = self.client.get(self.base + f'{question_id}/').data
        self.assertEqual((data['status'], data['answer_status']), ('COMPLETED', 'answered'))
        self.assertEqual(data['citations'][0]['version_id'], version.id)
        self.assertIn('/download/', data['citations'][0]['download_url'])
        self.assertEqual(self.client.post(self.base + f'{question_id}/feedback/', {'rating': 1}, format='json').status_code, 201)
        self.assertEqual(self.client.post(self.base + f'{question_id}/feedback/', {'rating': -1}, format='json').status_code, 200)
        delete_file(document)
        hidden = self.client.get(self.base + f'{question_id}/').data
        self.assertEqual(hidden['status'], 'SOURCE_UNAVAILABLE')
        self.assertIsNone(hidden['answer'])
        self.assertEqual(hidden['citations'], [])
        GroupMember.objects.filter(group=self.group, user=self.user).delete()
        self.assertEqual(self.client.get(self.base + f'{question_id}/').status_code, 404)

    def test_web_question_route_escapes_nickname_and_api_requires_auth(self):
        self.user.nickname = '<script>alert(1)</script>'
        self.user.save(update_fields=['nickname'])
        browser = Client()
        browser.force_login(self.user)
        page = browser.get(f'/web/groups/{self.group.id}/ask/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '질문하기')
        self.assertNotContains(page, '<script>alert(1)</script>', html=False)
        unauthenticated = APIClient()
        self.assertEqual(unauthenticated.post(self.base, {'question': 'test'}, format='json').status_code, 401)

    def test_no_index_abstains_without_search_or_model(self):
        question = self.make_question('없는 정책은?')
        with patch('ai_assistant.answers.search_group') as search, patch('ai_assistant.answers.answer_provider') as provider:
            process_question(question.id)
        search.assert_not_called()
        provider.assert_not_called()
        question.refresh_from_db()
        self.assertEqual((question.status, question.answer_status), ('COMPLETED', 'insufficient_evidence'))

    def test_citation_format_quote_and_html_are_checked(self):
        evidence = [{'chunk_id': 5, 'content': '<script>alert(1)</script> 근거 문장'}]
        for payload in ('invalid JSON', {'answer': 'x', 'answer_status': 'answered',
                          'citations': [{'chunk_id': 6, 'quote': '근거'}]},
                        {'answer': 'x', 'answer_status': 'answered',
                          'citations': [{'chunk_id': 5, 'quote': '위조 문장'}]}):
            with self.assertRaises(PermanentAnswerError):
                validate_answer(payload, evidence)
        valid = {'answer': '<script>alert(1)</script>', 'answer_status': 'answered',
                 'citations': [{'chunk_id': 5, 'quote': '<script>alert(1)</script>'}]}
        self.assertEqual(validate_answer(valid, evidence), [(5, '<script>alert(1)</script>')])
        with self.assertRaisesRegex(PermanentAnswerError, 'answer_not_in_citation'):
            validate_answer({'answer': '근거에 없는 결정', 'answer_status': 'answered',
                'citations': [{'chunk_id': 5, 'quote': '근거 문장'}]}, evidence)

    def test_delete_and_membership_revocation_during_generation(self):
        document, version, chunk = self.make_source()
        question = self.make_question()
        with patch('ai_assistant.answers.search_group', return_value=[
            {'chunk_id': chunk.id, 'content': chunk.content, 'file_id': document.id, 'version_id': version.id}]):
            with patch('ai_assistant.answers.answer_provider') as provider:
                def revoke(*_, **__):
                    GroupMember.objects.filter(group=self.group, user=self.user).delete()
                    return {'answer': '초대', 'answer_status': 'answered',
                            'citations': [{'chunk_id': chunk.id, 'quote': '초대'}]}, 3, 4
                provider.return_value.generate.side_effect = revoke
                process_question(question.id)
        question.refresh_from_db()
        self.assertEqual((question.status, question.error_code), ('FAILED', 'access_revoked'))
        self.assertEqual(AnswerCitation.objects.filter(question=question).count(), 0)

    def test_source_deleted_during_generation_fails_safely(self):
        document, version, chunk = self.make_source()
        question = self.make_question()
        hits = [{'chunk_id': chunk.id, 'content': chunk.content, 'file_id': document.id, 'version_id': version.id}]
        with patch('ai_assistant.answers.search_group', return_value=hits), patch('ai_assistant.answers.answer_provider') as provider:
            def remove(*_, **__):
                delete_file(document)
                return {'answer': '초대', 'answer_status': 'answered',
                        'citations': [{'chunk_id': chunk.id, 'quote': '초대'}]}, 3, 4
            provider.return_value.generate.side_effect = remove
            process_question(question.id)
        question.refresh_from_db()
        self.assertEqual((question.status, question.error_code), ('FAILED', 'source_changed'))
        self.assertFalse(AnswerCitation.objects.filter(question=question).exists())

    def test_transient_retry_bounded_and_duplicate_claim(self):
        document, version, chunk = self.make_source()
        question = self.make_question()
        hits = [{'chunk_id': chunk.id, 'content': chunk.content, 'file_id': document.id, 'version_id': version.id}]
        with patch('ai_assistant.answers.search_group', return_value=hits), patch('ai_assistant.answers.answer_provider') as provider:
            provider.return_value.generate.side_effect = TransientAnswerError('timeout')
            with patch('ai_assistant.tasks.answer_question.apply_async') as retry:
                process_question(question.id)
                question.refresh_from_db()
                self.assertEqual((question.status, question.attempts), ('QUEUED', 1))
                retry.assert_called_once()
                process_question(question.id)
        question.refresh_from_db()
        self.assertEqual((question.status, question.attempts), ('FAILED', 2))
        process_question(question.id)
        question.refresh_from_db()
        self.assertEqual(question.attempts, 2)

    def test_expired_openai_lease_does_not_retry_paid_call(self):
        question = self.make_question()
        question.status = Question.GENERATING
        question.provider_kind = 'openai'
        question.attempts = 1
        question.lease_until = timezone.now() - timedelta(seconds=1)
        question.save(update_fields=['status', 'provider_kind', 'attempts', 'lease_until'])
        with override_settings(AI_LLM_PROVIDER='openai'):
            process_question(question.id)
        question.refresh_from_db()
        self.assertEqual((question.status, question.error_code, question.attempts), ('FAILED', 'worker_timeout', 1))
