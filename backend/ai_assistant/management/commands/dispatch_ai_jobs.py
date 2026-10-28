from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from ai_assistant.models import AIProcessingJob
from ai_assistant.services import publish_job

class Command(BaseCommand):
    help = 'Re-publish pending jobs and reclaim expired worker leases.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        now = timezone.now()
        jobs = AIProcessingJob.objects.filter(status=AIProcessingJob.PENDING) | AIProcessingJob.objects.filter(
            status=AIProcessingJob.RUNNING, lease_until__lt=now)
        count = 0
        for job_id in jobs.order_by('id').values_list('id', flat=True)[:options['limit']]:
            publish_job(job_id)
            count += 1
        self.stdout.write(f'dispatched={count}')
