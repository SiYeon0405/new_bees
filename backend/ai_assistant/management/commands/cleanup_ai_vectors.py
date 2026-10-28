from django.core.management.base import BaseCommand
from ai_assistant.models import AIProcessingJob
from ai_assistant import vector_store

class Command(BaseCommand):
    help = 'Idempotently remove vectors for logically deleted files.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        store = vector_store.client()
        count = 0
        jobs = AIProcessingJob.objects.filter(file_version__file__deleted_at__isnull=False).order_by('id')[:options['limit']]
        for job in jobs:
            vector_store.delete_job_vectors(store, job)
            count += 1
        self.stdout.write(f'cleaned={count}')
