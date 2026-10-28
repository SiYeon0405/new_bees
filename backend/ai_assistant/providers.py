import hashlib
import json
import math
import os
from pathlib import Path
from django.conf import settings


class PermanentEmbeddingError(Exception):
    pass


class TransientEmbeddingError(Exception):
    pass


def reserve_real_evaluation_call(batch):
    """Reserve the approved request and byte budgets before an external call."""
    if os.getenv('AI_REAL_EVAL_ENABLED', '').lower() != 'true':
        return
    if (settings.AI_EMBEDDING_MODEL != 'text-embedding-3-small'
            or settings.AI_EMBEDDING_DIMENSION != 512
            or settings.AI_INDEX_REVISION != 'openai-eval-v1'
            or settings.DATABASES['default']['NAME'] != 'bees_openai_eval'):
        raise PermanentEmbeddingError('evaluation_configuration_mismatch')
    fixture = json.loads(Path('/app/search_eval_fixture.json').read_text(encoding='utf-8'))
    allowed = [version['text'] for document in fixture['documents'] for version in document['versions']]
    allowed.extend(question['query'] for question in fixture['questions'])
    if any(not any(text in source for source in allowed) for text in batch):
        raise PermanentEmbeddingError('evaluation_input_not_approved')
    byte_count = sum(len(text.encode('utf-8')) for text in batch)
    import redis
    ledger = redis.Redis.from_url(settings.CELERY_BROKER_URL)
    approved = ledger.eval('''
        local calls = tonumber(redis.call('GET', KEYS[1]) or '0')
        local bytes = tonumber(redis.call('GET', KEYS[2]) or '0')
        if calls + 1 > 22 or bytes + ARGV[1] > 12000 then return 0 end
        redis.call('INCR', KEYS[1])
        redis.call('INCRBY', KEYS[2], ARGV[1])
        return 1
    ''', 2, 'bees:openai_eval:request_count', 'bees:openai_eval:input_bytes', byte_count)
    if approved != 1:
        raise PermanentEmbeddingError('evaluation_budget_exceeded')


class FakeEmbeddings:
    def embed(self, texts, dimension, model=None):
        vectors = []
        for text in texts:
            seed = hashlib.sha256(text.encode('utf-8')).digest()
            values = [(seed[i % len(seed)] / 255.0) * 2 - 1 for i in range(dimension)]
            length = math.sqrt(sum(value * value for value in values)) or 1
            vectors.append([value / length for value in values])
        return vectors


class OpenAIEmbeddings:
    def embed(self, texts, dimension, model=None):
        from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError, AuthenticationError, BadRequestError, APIStatusError
        if not settings.OPENAI_API_KEY:
            raise PermanentEmbeddingError('provider_not_configured')
        if not texts or dimension < 1 or dimension > 2048:
            raise PermanentEmbeddingError('invalid_embedding_input')
        byte_lengths = [len(text.encode('utf-8')) for text in texts]
        if any(not text.strip() or size > 6000 for text, size in zip(texts, byte_lengths)):
            raise PermanentEmbeddingError('embedding_input_too_large')
        if sum(byte_lengths) > settings.AI_MAX_EMBEDDING_INPUT_BYTES:
            raise PermanentEmbeddingError('embedding_budget_exceeded')
        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30, max_retries=0)
        vectors = []
        self.usage_tokens = 0
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            reserve_real_evaluation_call(batch)
            try:
                response = client.embeddings.create(model=model or settings.AI_EMBEDDING_MODEL,
                    input=batch, dimensions=dimension, encoding_format='float')
            except RateLimitError as exc:
                body = getattr(exc, 'body', None)
                code = getattr(exc, 'code', None) or (body.get('code') if isinstance(body, dict) else getattr(body, 'code', None))
                if code in ('insufficient_quota', 'credit_balance_exhausted', 'organization_spend_limit_exceeded', 'project_spend_limit_exceeded'):
                    raise PermanentEmbeddingError('provider_quota_exhausted') from exc
                raise TransientEmbeddingError('provider_rate_limited') from exc
            except (APITimeoutError, APIConnectionError) as exc:
                raise TransientEmbeddingError('provider_temporarily_unavailable') from exc
            except (AuthenticationError, BadRequestError) as exc:
                raise PermanentEmbeddingError('provider_rejected_request') from exc
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    raise TransientEmbeddingError('provider_temporarily_unavailable') from exc
                raise PermanentEmbeddingError('provider_rejected_request') from exc
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch) or any(item.index != index or len(item.embedding) != dimension
                or any(not math.isfinite(value) for value in item.embedding) for index, item in enumerate(ordered)):
                raise PermanentEmbeddingError('invalid_provider_response')
            vectors.extend(item.embedding for item in ordered)
            self.usage_tokens += getattr(response.usage, 'total_tokens', 0) or 0
        return vectors


def provider(kind=None):
    kind = kind or settings.AI_EMBEDDING_PROVIDER
    if kind == 'fake':
        return FakeEmbeddings()
    if kind == 'openai':
        return OpenAIEmbeddings()
    raise PermanentEmbeddingError('provider_disabled')
