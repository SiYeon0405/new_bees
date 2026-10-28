from django.db.models import Q
from files.selectors import member_group
from .models import ActiveIndex, DocumentChunk
from .providers import provider
from . import vector_store


def search_group(user, group_id, query, limit=8, metrics=None):
    group = member_group(user, group_id)
    if not query.strip():
        return []
    active = list(ActiveIndex.objects.select_related('file', 'job__file_version').filter(
        file__group=group, file__deleted_at__isnull=True, job__status='READY'))
    if not active:
        return []
    store = vector_store.client()
    results = []
    query_vectors = {}
    for item in active:
        job = item.job
        signature = (job.embedding_provider, job.embedding_model, job.embedding_dimension)
        if signature not in query_vectors:
            embedder = provider(job.embedding_provider)
            query_vectors[signature] = embedder.embed([query], job.embedding_dimension, job.embedding_model)[0]
            if metrics is not None:
                metrics['embedding_calls'] = metrics.get('embedding_calls', 0) + 1
                metrics['embedding_tokens'] = metrics.get('embedding_tokens', 0) + getattr(embedder, 'usage_tokens', 0)
        vector = query_vectors[signature]
        for point in vector_store.search_points(store, job, vector, limit * 3):
            chunk = DocumentChunk.objects.filter(pk=point.payload.get('chunk_id'), job=job).first()
            if chunk:
                results.append((point.score, chunk))
    results.sort(key=lambda pair: pair[0], reverse=True)
    validated = []
    for score, chunk in results:
        if not ActiveIndex.objects.filter(job=chunk.job, file__group__members__user=user,
                file__deleted_at__isnull=True, job__status='READY').exists():
            continue
        validated.append({'score': score, 'chunk_id': chunk.id, 'file_id': chunk.file_version.file_id,
                          'version_id': chunk.file_version_id, 'content': chunk.content,
                          'char_start': chunk.char_start, 'char_end': chunk.char_end})
        if len(validated) >= limit:
            break
    return validated
