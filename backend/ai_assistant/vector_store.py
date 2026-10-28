from django.conf import settings
from qdrant_client import QdrantClient, models


def client():
    return QdrantClient(url=settings.QDRANT_URL, timeout=15)


def ensure_collection(store, job):
    name = job.collection_name
    if not store.collection_exists(name):
        store.create_collection(name, vectors_config=models.VectorParams(size=job.embedding_dimension, distance=models.Distance.COSINE))
    config = store.get_collection(name)
    if config.config.params.vectors.size != job.embedding_dimension:
        raise ValueError('Qdrant dimension mismatch')
    for field in ('group_id', 'file_id', 'file_version_id', 'job_id', 'index_revision'):
        if field not in config.payload_schema:
            schema = models.PayloadSchemaType.KEYWORD if field == 'index_revision' else models.PayloadSchemaType.INTEGER
            store.create_payload_index(name, field_name=field, field_schema=schema, wait=True)


def upsert_chunks(store, job, chunks, vectors):
    file = job.file_version.file
    points = [models.PointStruct(id=str(chunk.point_id), vector=vector, payload={
        'group_id': file.group_id, 'file_id': file.id, 'file_version_id': job.file_version_id,
        'job_id': job.id, 'chunk_id': chunk.id, 'index_revision': job.index_revision,
    }) for chunk, vector in zip(chunks, vectors)]
    store.upsert(job.collection_name, points=points, wait=True)


def delete_job_vectors(store, job):
    ids = [str(value) for value in job.chunks.values_list('point_id', flat=True)]
    if ids and store.collection_exists(job.collection_name):
        store.delete(job.collection_name, points_selector=models.PointIdsList(points=ids), wait=True)


def search_points(store, job, vector, limit):
    return store.query_points(job.collection_name, query=vector,
        query_filter=models.Filter(must=[
            models.FieldCondition(key='group_id', match=models.MatchValue(value=job.file_version.file.group_id)),
            models.FieldCondition(key='job_id', match=models.MatchValue(value=job.id)),
        ]), limit=limit, with_payload=True).points
