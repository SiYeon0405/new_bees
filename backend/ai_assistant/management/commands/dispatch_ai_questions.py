from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ai_assistant.models import Question
from ai_assistant.answers import publish_question


class Command(BaseCommand):
    help = 'Re-publish queued questions and expired leases with bounded attempts.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        if not settings.AI_QA_ENABLED:
            self.stdout.write('disabled')
            return
        now = timezone.now()
        jobs = Question.objects.filter(status=Question.QUEUED) | Question.objects.filter(
            status=Question.GENERATING, lease_until__lt=now)
        ids = list(jobs.order_by('id').values_list('id', flat=True)[:max(0, min(options['limit'], 100))])
        for question_id in ids:
            publish_question(question_id)
        self.stdout.write(f'dispatched={len(ids)}')
