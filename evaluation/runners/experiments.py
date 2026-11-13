"""Retrieval ablations on the same dataset, without touching production defaults.

From captured app runs (local mode) every variant comes from the SAME request's recorded rankings:
  dense_only      app dense ranking (pgvector, k=10)
  bm25_only       app BM25 ranking (k=10)
  hybrid_rrf      RRF fusion order, i.e. reranking disabled
  hybrid_rerank   production: RRF then TinyBERT rerank (final top-4)
Offline mode recomputes bm25_only and bm25_rerank locally (no network, no embeddings).
Reference metrics use human-labelled gold chunk ids, so no judge cost is involved.
"""
import random
import time

from evaluation import config
from evaluation.metrics import ir, registry

VARIANTS = {
    'dense_only': 'dense_ranking',
    'bm25_only': 'sparse_ranking',
    'hybrid_rrf': 'fused_ranking',
    'hybrid_rerank': 'reranked_ranking',
}
BASELINE = 'hybrid_rerank'


def _scored_cases(cases):
    return [c for c in cases if c['golden'].get('gold_chunk_ids') and c.get('contexts')]


def ir_table(cases, k=config.FINAL_K, variants=VARIANTS):
    per_case = {}
    for name, field in variants.items():
        per_case[name] = {c['golden']['id']: ir.score_ranking(c['contexts'].get(field) or [], c['golden']['gold_chunk_ids'], k)
                          for c in _scored_cases(cases)}
    means = {name: ir.mean_scores(list(rows.values())) for name, rows in per_case.items()}
    return means, per_case


def candidate_recall(cases):
    """Did the gold chunk at least reach the candidate pool (dense@10, bm25@10, fused@12)?"""
    pools = {'dense@10': ('dense_ranking', 10), 'bm25@10': ('sparse_ranking', 10), 'fused@12': ('fused_ranking', 12)}
    out = {}
    for name, (field, k) in pools.items():
        rows = [ir.recall_at_k(c['contexts'].get(field) or [], c['golden']['gold_chunk_ids'], k) for c in _scored_cases(cases)]
        out[name] = sum(rows) / len(rows) if rows else None
    return out


def paired_bootstrap(a, b, samples=5000, seed=20261113):
    """95% CI for mean(b - a) over paired cases. Deterministic seed for reproducibility."""
    diffs = [y - x for x, y in zip(a, b)]
    if not diffs:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(samples))
    return {'mean_diff': sum(diffs) / len(diffs), 'ci95': [means[int(0.025 * samples)], means[int(0.975 * samples) - 1]],
            'n': len(diffs)}


def compare_to_baseline(per_case, metric='recall', baseline=BASELINE):
    """Each variant vs production on the same cases: tolerance verdict plus bootstrap CI."""
    rows = {}
    base = per_case.get(baseline, {})
    for name, cases in per_case.items():
        if name == baseline:
            continue
        ids = [i for i in cases if cases[i] is not None and base.get(i) is not None]
        a = [base[i][metric] for i in ids]
        b = [cases[i][metric] for i in ids]
        ci = paired_bootstrap(a, b)
        verdict = registry.compare(f'ir.{name}.{metric}', sum(a) / len(a) if a else None, sum(b) / len(b) if b else None)
        # Only call a difference real if the bootstrap interval excludes zero too.
        if ci and verdict != 'flat' and ci['ci95'][0] <= 0 <= ci['ci95'][1]:
            verdict = 'not significant'
        rows[name] = {'vs': baseline, 'metric': metric, 'verdict_for_variant': verdict, 'bootstrap': ci}
    return rows


def offline_variants(goldens, documents):
    """BM25 and BM25+rerank computed locally, for the fully offline mode."""
    from backend.core.guardrails import sanitize_text
    from backend.core.reranker import load_ranker
    from backend.core.retrieval import rerank_documents, sparse_candidates
    load_ranker()
    docs = [d.model_copy(update={'page_content': sanitize_text(d.page_content)}) for d in documents]
    cases = []
    for golden in goldens:
        query = sanitize_text(golden['question'])
        started = time.perf_counter()
        sparse = sparse_candidates(docs, query, 10)
        sparse_ms = (time.perf_counter() - started) * 1000
        reranked, rerank_ms = [], None
        if sparse:
            started = time.perf_counter()
            _, info = rerank_documents(query, sparse[:config.FUSED_K])
            rerank_ms = (time.perf_counter() - started) * 1000
            reranked = [s['chunk_id'] for s in info['scores']]
        cases.append({'golden': golden, 'contexts': {
            'sparse_ranking': [d.metadata['chunk_id'] for d in sparse], 'bm25_rerank_ranking': reranked},
            'timings': {'sparse_ms': round(sparse_ms, 3), 'rerank_ms': round(rerank_ms, 3) if rerank_ms is not None else None}})
    return cases


OFFLINE_VARIANTS = {'bm25_only': 'sparse_ranking', 'bm25_rerank': 'bm25_rerank_ranking'}
