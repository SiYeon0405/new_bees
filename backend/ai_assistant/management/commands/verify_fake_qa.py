import time

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from ai_assistant.answers import queue_question
from ai_assistant.models import AIProcessingJob, Question
from files.models import File
from files.services import create_version
from groups.models import Group, GroupMember
from users.models import User


class Command(BaseCommand):
    help = 'Exercise a real Celery worker with fake embeddings and fake answers in an isolated DB.'

    def handle(self, *args, **options):
        if not (settings.DATABASES['default']['NAME'] == 'bees_qa_validation'
                and settings.AI_EMBEDDING_PROVIDER == 'fake' and settings.AI_LLM_PROVIDER == 'fake'
                and settings.AI_QA_ENABLED and settings.AI_INDEX_REVISION == 'qa-validation-v1'
                and str(settings.MEDIA_ROOT) == '/app/private_media'):
            raise CommandError('Dedicated fake QA validation settings required')
        if User.objects.exists() or Group.objects.exists() or File.objects.exists() or Question.objects.exists():
            raise CommandError('Validation DB already has data; no existing rows were changed')

        def owner(key):
            user = User.objects.create_user(email=f'qa-{key}@example.invalid', nickname=f'qa-{key}',
                                            password=User.objects.make_random_password())
            group = Group.objects.create(name=f'qa-{key}', owner=user)
            GroupMember.objects.create(group=group, user=user, role='owner')
            return user, group

        alpha_user, alpha = owner('alpha')
        beta_user, beta = owner('beta')
        sources = [(alpha_user, alpha, 'auth.md', '로그인 토큰은 1일 뒤 만료한다.'),
                   (alpha_user, alpha, 'group.md', '초대 코드는 24시간 뒤 만료한다.'),
                   (beta_user, beta, 'private.md', '베타 배포 승인 담당자는 민지다.')]
        for user, group, name, content in sources:
            _, version = create_version(group, user, SimpleUploadedFile(name, content.encode('utf-8')))
            job = AIProcessingJob.objects.get(file_version=version)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                job.refresh_from_db()
                if job.status in ('READY', 'FAILED'):
                    break
                time.sleep(0.5)
            if job.status != 'READY':
                raise CommandError(f'Fake worker indexing failed: {job.status}')
        cases = [(alpha_user, alpha, 'invite code 만료 시간은?', 'answered'),
                 (alpha_user, alpha, '베타 배포 승인 담당자는 누구?', 'insufficient_evidence'),
                 (beta_user, beta, '베타 배포 승인 담당자는 누구?', 'answered')]
        summaries = []
        for user, group, text, expected in cases:
            question, _ = queue_question(user, group, text)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                question.refresh_from_db()
                if question.status in ('COMPLETED', 'FAILED'):
                    break
                time.sleep(0.5)
            if question.status != 'COMPLETED' or question.answer_status != expected:
                raise CommandError(f'Fake worker answer failed: {question.status}/{question.answer_status}')
            summaries.append({'status': question.status, 'answer_status': question.answer_status,
                              'citations': question.citations.count(), 'attempts': question.attempts})
        self.stdout.write(str({'ready_indexes': AIProcessingJob.objects.filter(status='READY').count(),
                               'questions': summaries, 'provider': 'fake'}))
