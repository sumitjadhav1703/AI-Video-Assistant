"""Fixed Gemini embedding space and per-job PGVector collections."""
import math
import os
import time
from types import SimpleNamespace

import httpx
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector

from .. import db
from ..db import get_sqlalchemy_url
from ..usage_limits import require_provider_calls
from .llm_gateway import validate_transcript, current_operation, assert_private_runtime
from .guardrails import sanitize_text
from . import provider_budget

EMBEDDING_MODEL = 'gemini-embedding-001'
EMBEDDING_DIMENSION = 768


def collection_for(job_id: str) -> str:
    if not job_id:
        raise ValueError('job_id is required — vector stores are never shared across jobs')
    return f'job_{job_id}'


def normalize_embedding(values):
    if not isinstance(values, list) or len(values) != EMBEDDING_DIMENSION:
        raise ValueError('Embedding dimension does not match the immutable 768-dimensional space')
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError('Embedding must contain finite numeric values')
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0 or not math.isfinite(norm):
        raise ValueError('Embedding has invalid magnitude')
    return [value / norm for value in values]


def _embedding_route():
    require_provider_calls()
    assert_private_runtime()
    if (os.getenv('ENABLE_GEMINI_EMBEDDINGS', '').lower() != 'true' or
            os.getenv('GEMINI_EMBEDDINGS_VERIFIED_FREE', '').lower() != 'true' or
            not os.getenv('GEMINI_API_KEY', '').strip()):
        raise RuntimeError('Gemini embeddings require explicit verified free account enablement')
    try:
        limits = {name.lower(): int(os.environ[f'GEMINI_EMBEDDINGS_{name}']) for name in ('RPM','TPM','RPD')}
        if min(limits.values()) <= 0:
            raise ValueError()
    except (KeyError, ValueError):
        raise ValueError('Explicit Gemini embedding account rate limits are required') from None
    return SimpleNamespace(alias='gemini-embeddings', provider='gemini', input_limit_tokens=60000, **limits)


class GeminiEmbeddings(Embeddings):
    def _embed(self, texts, task_type):
        route = _embedding_route()
        if not texts:
            return []
        if len(texts) > 100:
            raise ValueError('Embedding batches are limited to 100 documents')
        sanitized = [sanitize_text(text) for text in texts]
        # UTF-8 bytes bound token count without fetching another tokenizer/model.
        bounds = [len(text.encode('utf-8')) for text in sanitized]
        if any(bound == 0 or bound > 2048 for bound in bounds):
            raise ValueError('Embedding input exceeds its conservative 2048-token bound')
        attempt_id = provider_budget.reserve_attempt(current_operation(), route, sum(bounds), output_tokens=0)
        requests = [{'model': f'models/{EMBEDDING_MODEL}', 'content': {'parts': [{'text': text}]},
                     'taskType': task_type, 'outputDimensionality': EMBEDDING_DIMENSION} for text in sanitized]
        started = time.monotonic()
        try:
            with httpx.Client(timeout=60, transport=httpx.HTTPTransport(retries=0), trust_env=False) as client:
                response = client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:batchEmbedContents',
                                       headers={'x-goog-api-key': os.environ['GEMINI_API_KEY']}, json={'requests': requests})
                response.raise_for_status()
                payload = response.json()
                values = payload['embeddings']
            if len(values) != len(texts):
                raise ValueError('Embedding response count mismatch')
            embeddings = [normalize_embedding(item['values']) for item in values]
        except Exception:
            provider_budget.record_attempt_result(attempt_id, 'failed', max(0, int((time.monotonic() - started) * 1000)))
            raise RuntimeError('Gemini embeddings request failed; no fallback was attempted.') from None
        usage = payload.get('usageMetadata', {})
        reported = usage.get('promptTokenCount') if isinstance(usage, dict) else None
        if type(reported) is not int or reported < 0:
            reported = None
        provider_budget.record_attempt_result(attempt_id, 'success', max(0, int((time.monotonic() - started) * 1000)),
                                              input_tokens=reported, output_tokens=0)
        return embeddings

    def embed_documents(self, texts):
        return self._embed(texts, 'RETRIEVAL_DOCUMENT')

    def embed_query(self, text):
        return self._embed([text], 'RETRIEVAL_QUERY')[0]


def get_embeddings():
    _embedding_route()
    return GeminiEmbeddings()


def build_vector_store(transcript: str, job_id: str, documents=None) -> PGVector:
    validate_transcript(transcript)
    if documents is None:
        from .chunks import prepare_documents
        documents = prepare_documents([{'text':transcript, 'start_ms':None,'end_ms':None,'timing_precision':'unknown'}], job_id)
    if not documents or any(doc.metadata.get('job_id') != job_id or doc.id != doc.metadata.get('chunk_id') or sanitize_text(doc.page_content) != doc.page_content for doc in documents):
        raise ValueError('Invalid sanitized job documents')
    vector_store = PGVector.from_documents(documents=documents, embedding=get_embeddings(),
        ids=[doc.metadata['chunk_id'] for doc in documents], collection_name=collection_for(job_id),
        connection=get_sqlalchemy_url(), use_jsonb=True)
    db.save_chunks(job_id, documents)
    return vector_store


def load_vector_store(job_id: str) -> PGVector:
    job = db.get_job(job_id)
    if not job or (job.get('retrieval_version'),job.get('embedding_model'),job.get('embedding_dimension')) != ('hybrid-v1',EMBEDDING_MODEL,EMBEDDING_DIMENSION):
        from .retrieval import RetrievalUnavailable
        raise RetrievalUnavailable('This legacy index must be reprocessed before hybrid chat.')
    return PGVector(collection_name=collection_for(job_id), embeddings=get_embeddings(),
                    connection=get_sqlalchemy_url(), use_jsonb=True)


def get_retriever(vector_store, k=4):
    return vector_store.as_retriever(search_type='similarity', search_kwargs={'k':k})


def delete_vector_store(job_id: str) -> None:
    collection = collection_for(job_id)
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('langchain_pg_collection') AS table_name")
        if cur.fetchone()['table_name']:
            cur.execute('DELETE FROM langchain_pg_collection WHERE name = %s', (collection,))
        cur.execute("SELECT to_regclass('transcript_chunks') AS table_name")
        if cur.fetchone()['table_name']:
            cur.execute('DELETE FROM transcript_chunks WHERE job_id=%s', (job_id,))
        conn.commit()
