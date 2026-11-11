"""Job-scoped sparse/dense retrieval with required local reranking."""
import re
import unicodedata
from collections import defaultdict
from .guardrails import sanitize_text
from ..usage_limits import LimitExceeded
from .provider_budget import JobBudgetExceeded
from .telemetry import duration, metric

RETRIEVAL_VERSION = 'hybrid-v1'
TOKENIZATION_VERSION = 'nfkc-casefold-word-v1'


class RetrievalUnavailable(RuntimeError):
    """Retrieval cannot satisfy its isolation/model contract (HTTP 503)."""


def tokenize(text):
    return re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold())


def _key(document):
    return (document.metadata['ordinal'], document.metadata['chunk_id'])


def sparse_candidates(documents, query, k=10):
    from langchain_community.retrievers import BM25Retriever
    tokens = tokenize(query)
    documents = [doc for doc in documents if tokenize(doc.page_content)]
    if not documents or not tokens:
        return []
    retriever = BM25Retriever.from_documents(documents, preprocess_func=tokenize, k=k)
    scores = retriever.vectorizer.get_scores(tokens)
    # BM25 IDF can legitimately be zero or negative; lexical overlap is the match gate.
    ranked = [(doc, float(score)) for doc, score in zip(documents, scores)
              if set(tokens).intersection(tokenize(doc.page_content))]
    ranked.sort(key=lambda item: (-item[1], *_key(item[0])))
    return [doc for doc, _ in ranked[:k]]


def reciprocal_rank_fusion(rankings, k=12):
    scores = defaultdict(float)
    documents = {}
    for ranking in rankings:
        seen = set()
        for rank, doc in enumerate(ranking, 1):
            chunk_id = doc.metadata['chunk_id']
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            documents[chunk_id] = doc
            scores[chunk_id] += 1 / (60 + rank)
    return sorted(documents.values(), key=lambda doc: (-scores[doc.metadata['chunk_id']], *_key(doc)))[:k]


def rerank_documents(query, documents):
    from .reranker import rerank_documents as rerank
    return rerank(query, documents)


def hybrid_retrieve(query, job_id, documents, vector_store):
    try:
        query = sanitize_text(query)
        documents = [doc.model_copy(update={'page_content': sanitize_text(doc.page_content)}) for doc in documents]
        owned = {doc.metadata['chunk_id']: doc for doc in documents}
        if len(owned) != len(documents) or any(doc.metadata['job_id'] != job_id for doc in documents):
            raise RetrievalUnavailable('Chunk corpus failed isolation checks.')
        dense = []
        with duration('dense_retrieval'):
            hits = vector_store.similarity_search(query, k=10, filter={'job_id': job_id})
        for hit in hits:
            chunk_id = hit.metadata.get('chunk_id')
            if chunk_id not in owned or hit.metadata.get('job_id') != job_id or (hit.id and hit.id != chunk_id):
                raise RetrievalUnavailable('Dense results failed isolation checks.')
            if owned[chunk_id] not in dense:
                dense.append(owned[chunk_id])
        with duration('sparse_retrieval'):
            sparse = sparse_candidates(documents, query, 10)
        with duration('rrf'):
            fused = reciprocal_rank_fusion([dense, sparse], 12)
        metric('retrieval_candidates', dense=len(dense), sparse=len(sparse), fused=len(fused))
        if not fused:
            return [], {'version': RETRIEVAL_VERSION, 'tokenization_version': TOKENIZATION_VERSION,
                        'dense_count': 0, 'sparse_count': 0, 'fused_count': 0, 'final_count': 0}
        with duration('rerank'):
            final, rerank_info = rerank_documents(query, fused)
        if (not final or len(final) > 4 or len({d.metadata['chunk_id'] for d in final}) != len(final)
                or any(doc.metadata['chunk_id'] not in {d.metadata['chunk_id'] for d in fused} for doc in final)):
            raise RetrievalUnavailable('Reranker returned invalid results.')
        final = [owned[doc.metadata['chunk_id']] for doc in final]
        metric('retrieval_results', final=len(final))
        dense_ranks = {doc.metadata['chunk_id']: i for i, doc in enumerate(dense, 1)}
        sparse_ranks = {doc.metadata['chunk_id']: i for i, doc in enumerate(sparse, 1)}
        fusion = []
        for rank, doc in enumerate(fused, 1):
            chunk_id = doc.metadata['chunk_id']
            fusion.append({'chunk_id': chunk_id, 'rank': rank,
                           'rrf_score': sum(1 / (60 + ranks[chunk_id]) for ranks in (dense_ranks, sparse_ranks) if chunk_id in ranks)})
        return final, {'version': RETRIEVAL_VERSION, 'tokenization_version': TOKENIZATION_VERSION,
                       'dense_count': len(dense), 'sparse_count': len(sparse), 'fused_count': len(fused),
                       'final_count': len(final), 'chunk_ids': [doc.metadata['chunk_id'] for doc in final],
                       'dense_ranks': dense_ranks, 'sparse_ranks': sparse_ranks, 'fusion': fusion,
                       'reranker': rerank_info}
    except (RetrievalUnavailable, LimitExceeded, JobBudgetExceeded):
        raise
    except Exception as exc:
        raise RetrievalUnavailable('Hybrid retrieval is unavailable.') from exc
