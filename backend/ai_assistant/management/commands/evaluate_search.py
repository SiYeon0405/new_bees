import json
import os
import time
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from files.services import create_version
from files.models import File
from groups.models import Group, GroupMember
from users.models import User
from ai_assistant.models import AIProcessingJob
from ai_assistant.search import search_group


FIXTURE = Path('/app/search_eval_fixture.json')
MAX_FIXTURE_BYTES = 12000
PRICE_PER_MILLION_TOKENS = 0.02


def load_fixture(path):
    payload = json.loads(path.read_text(encoding='utf-8'))
    documents, questions = payload['documents'], payload['questions']
    versions = [version for document in documents for version in document['versions']]
    total_bytes = sum(len(version['text'].encode('utf-8')) for version in versions)
    total_bytes += sum(len(item['query'].encode('utf-8')) for item in questions)
    if len(documents) != 6 or len(versions) != 7 or len(questions) != 15 or total_bytes > MAX_FIXTURE_BYTES:
        raise CommandError('Unexpected evaluation fixture size')
    keys = {document['key'] for document in documents}
    if len(keys) != 6 or any(item['expected_file'] not in keys | {None} for item in questions):
        raise CommandError('Invalid evaluation fixture references')
    for item in questions:
        if item['expected_file'] is None:
            continue
        document = next(document for document in documents if document['key'] == item['expected_file'])
        version = next((version for version in document['versions'] if version['number'] == item['expected_version']), None)
        if version is None or item['evidence'] not in version['text']:
            raise CommandError(f"Invalid evidence for {item['id']}")
    return payload, total_bytes


class Command(BaseCommand):
    help = 'Run the isolated paid embedding evaluation only after explicit approval.'

    def add_arguments(self, parser):
        parser.add_argument('--allow-paid-calls', action='store_true')
        parser.add_argument('--fixture', type=Path, default=FIXTURE)
        parser.add_argument('--output', type=Path, default=Path('/app/private_media/search-evaluation.json'))

    def handle(self, *args, **options):
        payload, total_bytes = load_fixture(options['fixture'])
        if not options['allow_paid_calls']:
            self.stdout.write(f'Prepared: 7 synthetic versions, 15 questions, {total_bytes} UTF-8 bytes; no external calls made.')
            return
        if not (os.getenv('AI_REAL_EVAL_ENABLED', '').lower() == 'true'
                and settings.AI_INDEX_ENABLED and settings.AI_EMBEDDING_PROVIDER == 'openai'
                and settings.AI_EMBEDDING_MODEL == 'text-embedding-3-small'
                and settings.AI_EMBEDDING_DIMENSION == 512
                and settings.AI_INDEX_REVISION == 'openai-eval-v1'
                and settings.DATABASES['default']['NAME'] == 'bees_openai_eval'
                and str(settings.MEDIA_ROOT) == '/app/private_media'
                and settings.OPENAI_API_KEY):
            raise CommandError('Isolated real evaluation settings are required')
        if User.objects.exists() or Group.objects.exists() or File.objects.exists() or AIProcessingJob.objects.exists():
            raise CommandError('Evaluation DB must have no existing users, groups, files or AI jobs; existing data was not changed')
        import redis
        ledger = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        if int(ledger.get('bees:openai_eval:request_count') or 0):
            raise CommandError('Previous evaluation calls already exist; no new paid calls were made')
        users, groups = {}, {}
        for group_key in ('alpha', 'beta'):
            user = User.objects.create_user(email=f'eval-{group_key}@example.invalid',
                                            nickname=f'eval-{group_key}', password=User.objects.make_random_password())
            group = Group.objects.create(name=f'eval-{group_key}', owner=user)
            GroupMember.objects.create(group=group, user=user, role='owner')
            users[group_key], groups[group_key] = user, group
        documents = {}
        job_ids = []
        for entry in payload['documents']:
            group_key = entry['group']
            document = None
            for version_data in entry['versions']:
                upload = SimpleUploadedFile(f"{entry['key']}.md", version_data['text'].encode('utf-8'))
                document, version = create_version(groups[group_key], users[group_key], upload, document)
                job = AIProcessingJob.objects.get(file_version=version)
                job_ids.append(job.id)
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    job.refresh_from_db()
                    if job.status in (AIProcessingJob.READY, AIProcessingJob.FAILED):
                        break
                    time.sleep(1)
                if job.status != AIProcessingJob.READY:
                    raise CommandError(f'Indexing did not complete for {entry["key"]} version {version_data["number"]}: {job.status}')
                documents[(entry['key'], version_data['number'])] = (document.id, version.id)
        outcomes = []
        reverse_documents = {(file_id, version_id): (key, number)
                             for (key, number), (file_id, version_id) in documents.items()}
        for question in payload['questions']:
            metrics = {}
            started = time.monotonic()
            hits = search_group(users[question['group']], groups[question['group']].id, question['query'], limit=5, metrics=metrics)
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            expected = documents.get((question['expected_file'], question['expected_version']))
            evidence_hit = bool(expected and any(hit['file_id'] == expected[0] and hit['version_id'] == expected[1]
                                                 and question['evidence'] in hit['content'] for hit in hits))
            wrong_version = bool(expected and any(hit['file_id'] == expected[0] and hit['version_id'] != expected[1] for hit in hits))
            group_files = {file_id for (key, _), (file_id, _) in documents.items()
                           if next(entry for entry in payload['documents'] if entry['key'] == key)['group'] == question['group']}
            leakage = any(hit['file_id'] not in group_files for hit in hits)
            outcomes.append({'id': question['id'], 'type': question['type'], 'evidence_hit_at_5': evidence_hit,
                             'wrong_version': wrong_version, 'cross_group_leakage': leakage,
                             'returned_hits': len(hits), 'latency_ms': latency_ms,
                             'top_hits': [{'rank': rank, 'document': reverse_documents.get((hit['file_id'], hit['version_id']), ('unknown', None))[0],
                                           'version': reverse_documents.get((hit['file_id'], hit['version_id']), ('unknown', None))[1],
                                           'score': round(hit['score'], 4),
                                           'contains_expected_evidence': bool(question['evidence'] and question['evidence'] in hit['content'])}
                                          for rank, hit in enumerate(hits, 1)],
                             'query_tokens': metrics.get('embedding_tokens', 0),
                             'query_calls': metrics.get('embedding_calls', 0)})
        document_tokens = sum(AIProcessingJob.objects.get(pk=job_id).embedding_tokens for job_id in job_ids)
        query_tokens = sum(row['query_tokens'] for row in outcomes)
        answerable = [row for row, question in zip(outcomes, payload['questions']) if question['expected_file']]
        report = {'provider': 'openai', 'model': settings.AI_EMBEDDING_MODEL,
                  'dimension': settings.AI_EMBEDDING_DIMENSION, 'index_revision': settings.AI_INDEX_REVISION,
                  'document_calls': len(job_ids), 'query_calls': sum(row['query_calls'] for row in outcomes),
                  'document_tokens': document_tokens, 'query_tokens': query_tokens,
                  'reserved_api_requests': int(ledger.get('bees:openai_eval:request_count') or 0),
                  'reserved_input_bytes': int(ledger.get('bees:openai_eval:input_bytes') or 0),
                  'actual_billed_usd': None,
                  'estimated_usd': round((document_tokens + query_tokens) * PRICE_PER_MILLION_TOKENS / 1_000_000, 8),
                  'recall_at_5': sum(row['evidence_hit_at_5'] for row in answerable) / len(answerable),
                  'wrong_version_count': sum(row['wrong_version'] for row in outcomes),
                  'cross_group_leakage_count': sum(row['cross_group_leakage'] for row in outcomes),
                  'questions': outcomes}
        options['output'].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(json.dumps(report, ensure_ascii=False))
