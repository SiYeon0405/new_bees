from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from files.models import FileVersion
from ai_assistant.services import queue_version, configuration
from ai_assistant.models import AIProcessingJob

class Command(BaseCommand):
    help = 'Queue unindexed, non-deleted versions for the current embedding configuration.'

    def add_arguments(self, parser):
        parser.add_argument('--group-id', type=int, required=True)
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--current-only', action='store_true')

    def handle(self, *args, **options):
        if not settings.AI_INDEX_ENABLED:
            raise CommandError('AI_INDEX_ENABLED must be true')
        key, _ = configuration()
        versions = FileVersion.objects.filter(file__group_id=options['group_id'],
            file__deleted_at__isnull=True, sha256__isnull=False).exclude(sha256='').exclude(
            ai_jobs__config_key=key)
        if options['current_only']:
            versions = versions.filter(version_number=F('file__current_version_number'))
        versions = versions.order_by('id')[:options['limit']]
        ids = list(versions.values_list('id', flat=True))
        if not options['dry_run']:
            for version in FileVersion.objects.filter(id__in=ids):
                with transaction.atomic():
                    queue_version(version)
        self.stdout.write(f'queued={len(ids)} dry_run={options["dry_run"]}')
