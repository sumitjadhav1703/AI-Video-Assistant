"""Build and query per-job PGVector collections using a pinned embedding route."""
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector

from .. import db
from ..db import collection_for, get_sqlalchemy_url
from ..usage_limits import require_provider_calls
from . import provider_budget
from .embedding_routes import (
    EMBEDDING_SPACES, EmbeddingRouteUnavailable, EmbeddingRetryable,
    batch_input_bound, configured_embedding_routes, embed_batch,
)
from .guardrails import sanitize_text
from .llm_gateway import assert_private_runtime, current_operation, validate_transcript
from .retrieval import RetrievalUnavailable

GEMINI_ROUTE = 'gemini-embeddings'


def available_embedding_routes():
    require_provider_calls()
    assert_private_runtime()
    return tuple(route for route in configured_embedding_routes() if route.available())


def _document_batches(route, texts):
    for start in range(0, len(texts), route.batch_size):
        yield texts[start:start + route.batch_size]


def _forecast_route(route, texts, generation_stages):
    attempts = [(route, batch_input_bound(route, batch), 0)
                for batch in _document_batches(route, texts)]
    attempts.append((route, batch_input_bound(route, ['x' * 2048], query=True), 0))
    return provider_budget.forecast_attempts(current_operation(), attempts,
                                             generation_stages=generation_stages)


def forecast_embeddings(texts, generation_stages):
    failure = None
    for route in available_embedding_routes():
        try:
            return _forecast_route(route, texts, generation_stages)
        except (provider_budget.RouteQuotaExceeded, provider_budget.JobBudgetExceeded) as error:
            failure = error
    if failure is not None:
        raise failure
    raise EmbeddingRouteUnavailable('Configure a verified embedding route before processing.')


class RouteEmbeddings(Embeddings):
    def __init__(self, route):
        self.route = route

    def embed_documents(self, texts):
        return [vector for batch in _document_batches(self.route, texts)
                for vector in embed_batch(self.route, batch)]

    def embed_query(self, text):
        return embed_batch(self.route, [text], query=True)[0]


def get_embeddings(route_id=None):
    for route in available_embedding_routes():
        if route_id is None or route_id == route.alias:
            return RouteEmbeddings(route)
    raise EmbeddingRouteUnavailable('The required embedding route is unavailable.')


def build_vector_store(transcript: str, job_id: str, documents=None) -> PGVector:
    validate_transcript(transcript)
    if current_operation() != job_id:
        raise RetrievalUnavailable('The embedding operation does not match the session.')
    if documents is None:
        from .chunks import prepare_documents
        documents = prepare_documents([{'text': transcript, 'start_ms': None, 'end_ms': None,
                                        'timing_precision': 'unknown'}], job_id)
    if not documents or any(doc.metadata.get('job_id') != job_id or doc.id != doc.metadata.get('chunk_id')
                            or sanitize_text(doc.page_content) != doc.page_content for doc in documents):
        raise ValueError('Invalid sanitized job documents')
    texts = [doc.page_content for doc in documents]
    failure = None
    for route in available_embedding_routes():
        try:
            _forecast_route(route, texts, ())
            embeddings = RouteEmbeddings(route)
            vectors = embeddings.embed_documents(texts)
        except (EmbeddingRetryable, provider_budget.RouteQuotaExceeded, provider_budget.JobBudgetExceeded) as error:
            failure = error
            continue

        # The whole corpus has been embedded in one space before any index writes.
        vector_store = PGVector(collection_name=collection_for(job_id), embeddings=embeddings,
                                connection=get_sqlalchemy_url(), use_jsonb=True)
        vector_store.add_embeddings(texts=texts, embeddings=vectors,
                                    metadatas=[doc.metadata for doc in documents],
                                    ids=[doc.id for doc in documents])
        db.save_chunks(job_id, documents, embedding_route=route.alias)
        return vector_store

    if failure is not None:
        raise failure
    raise EmbeddingRouteUnavailable('Configure a verified embedding route before processing.')


def load_vector_store(job_id: str) -> PGVector:
    if current_operation() != job_id:
        raise RetrievalUnavailable('The embedding operation does not match the session.')
    job = db.get_job(job_id)
    if not job or job.get('retrieval_version') != 'hybrid-v1':
        raise RetrievalUnavailable('This legacy index must be reprocessed before hybrid chat.')
    route_id = job.get('embedding_route')
    space = (job.get('embedding_model'), job.get('embedding_dimension'))
    if route_id is None and space == EMBEDDING_SPACES[GEMINI_ROUTE]:
        route_id = GEMINI_ROUTE
    if space != EMBEDDING_SPACES.get(route_id):
        raise RetrievalUnavailable('This session has an unsupported embedding index.')
    return PGVector(collection_name=collection_for(job_id), embeddings=get_embeddings(route_id),
                    connection=get_sqlalchemy_url(), use_jsonb=True)
