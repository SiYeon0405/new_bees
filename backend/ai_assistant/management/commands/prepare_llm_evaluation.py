import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ai_assistant.answer_provider import build_openai_request
from ai_assistant.llm_evaluation_budget import MAX_REQUEST_BYTES, MAX_REQUESTS, MAX_OUTPUT_TOKENS


class Command(BaseCommand):
    help = 'Offline inspection of approved synthetic LLM requests. Never calls an external API.'

    def add_arguments(self, parser):
        parser.add_argument('--fixture', type=Path, default=Path('/app/llm_eval_fixture.json'))

    def handle(self, *args, **options):
        fixture = json.loads(options['fixture'].read_text(encoding='utf-8'))
        cases = fixture['cases']
        if len(cases) != MAX_REQUESTS or len({case['id'] for case in cases}) != MAX_REQUESTS:
            raise CommandError('Unexpected synthetic evaluation cases')
        sizes = []
        for case in cases:
            request = build_openai_request(case['question'], case['evidence'],
                                           model='gpt-4o-mini', max_output_tokens=MAX_OUTPUT_TOKENS)
            payload_bytes = len(json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
            if payload_bytes > MAX_REQUEST_BYTES:
                raise CommandError(f"Case {case['id']} exceeds 3000 UTF-8 request bytes")
            sizes.append((case['id'], payload_bytes))
        self.stdout.write(str({'cases': sizes, 'count': len(sizes), 'output_limit': MAX_OUTPUT_TOKENS,
                               'external_calls': 0, 'exact_billable_input_tokens': 'unverified'}))
