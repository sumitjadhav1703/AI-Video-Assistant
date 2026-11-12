"""Offline functional retrieval fixture and real local reranker measurements."""
import argparse
import json
import os
import platform
import resource
import socket
import sys
import time
from importlib.metadata import version
from unittest.mock import patch


def metrics(ranking, relevant, k):
    top = ranking[:k]
    return {'recall_at_k': len(set(top) & relevant) / len(relevant),
            'reciprocal_rank': next((1 / i for i, item in enumerate(top, 1) if item in relevant), 0.0)}


def run():
    from langchain_core.documents import Document
    from backend.core.retrieval import reciprocal_rank_fusion, sparse_candidates
    from backend.core.reranker import load_ranker, rerank_documents
    texts = [
        'Alice will ship the demo Friday.', 'The budget review is Monday.',
        'Bob owns the database migration.', 'The launch is postponed until Tuesday.',
        'Carol will prepare the slides.', 'The deployment uses PostgreSQL.',
        'The team discussed a customer interview.', 'Testing starts on Thursday.',
        'Security review is assigned to Dana.', 'The office closes at six.',
        'The release notes need editing.', 'The team agreed to use Python.',
    ]
    docs = [Document(id=str(i), page_content=text,
                     metadata={'ordinal': i, 'chunk_id': str(i)}) for i, text in enumerate(texts)]
    cases = [
        ('Who ships the demo?', {'0'}, [2, 0, 4, 6]),
        ('When is the budget review?', {'1'}, [3, 1, 5, 7]),
        ('Who owns database migration?', {'2'}, [5, 2, 8, 10]),
    ]
    started = time.perf_counter()
    first = load_ranker()
    cold_load = time.perf_counter() - started
    started = time.perf_counter()
    second = load_ranker()
    warm_load = time.perf_counter() - started
    stress = [doc.model_copy(update={'page_content': doc.page_content + ' repeated words' * 600}) for doc in docs]
    encoded_lengths = [len(first.tokenizer.encode('Who ships the demo?', doc.page_content).ids) for doc in stress]
    started = time.perf_counter()
    _, cold_info = rerank_documents('Who ships the demo?', stress)
    cold_inference = time.perf_counter() - started
    started = time.perf_counter()
    _, warm_info = rerank_documents('Who ships the demo?', stress)
    warm_inference = time.perf_counter() - started
    assert first is second and cold_info['truncated_count'] == 12 and warm_info['max_tokens'] == 512
    assert max(encoded_lengths) <= 512
    comparisons = []
    for query, relevant, dense_ids in cases:
        dense = [docs[i] for i in dense_ids]
        sparse = sparse_candidates(docs, query, 10)
        fused = reciprocal_rank_fusion([dense, sparse], 12)
        ranked, _ = rerank_documents(query, fused)
        stages = {'synthetic_dense_fixture': dense, 'bm25': sparse, 'rrf': fused, 'rrf_then_rerank': ranked}
        comparisons.append({'query': query, 'relevant_ids': sorted(relevant),
                            'stages': {name: {'ranking': [d.id for d in ranking],
                                              **metrics([d.id for d in ranking], relevant, 4)}
                                       for name, ranking in stages.items()}})
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {'scope': 'Synthetic labelled functional fixture; dense rankings are precomputed, not provider embeddings or evidence of retrieval quality.',
            'environment': {'platform': platform.platform(), 'architecture': platform.machine(),
                            'python': sys.version, 'versions': {name: version(name) for name in ('FlashRank', 'onnxruntime', 'tokenizers', 'langchain-community')}},
            'reranker': {'singleton_reused': first is second, 'cold_load_seconds': cold_load,
                         'warm_load_seconds': warm_load, 'cold_inference_seconds': cold_inference,
                         'warm_inference_seconds': warm_inference, 'candidates': 12,
                         'max_tokens': cold_info['max_tokens'], 'max_encoded_tokens': max(encoded_lengths),
                         'truncated_count': cold_info['truncated_count']},
            'process_peak_rss': {'value': peak, 'unit': 'bytes' if sys.platform == 'darwin' else 'KiB' if sys.platform.startswith('linux') else 'platform-dependent ru_maxrss units'},
            'comparisons': comparisons}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--full-service', action='store_true', help='import backend API and gateway libraries before measurement')
    parser.add_argument('--require-linux', action='store_true')
    parser.add_argument('--max-rss-mib', type=float)
    args = parser.parse_args()
    if args.require_linux and not sys.platform.startswith('linux'):
        parser.error('--require-linux requires Linux')
    if args.max_rss_mib is not None and (not 0 < args.max_rss_mib < float('inf') or sys.platform not in ('darwin', 'linux')):
        parser.error('--max-rss-mib requires a positive finite limit and macOS or Linux')
    def no_network(*args, **kwargs):
        raise RuntimeError('Network access is disabled in this offline benchmark')
    offline_env = {'PATH': os.defpath, 'ENABLE_PROVIDER_CALLS': 'false', 'LANGSMITH_TRACING': 'false',
                   'LANGCHAIN_TRACING_V2': 'false', 'LITELLM_TELEMETRY': 'false',
                   'LITELLM_LOCAL_MODEL_COST_MAP': 'true', 'DO_NOT_TRACK': '1'}
    with patch.dict(os.environ, offline_env, clear=True), patch('dotenv.load_dotenv', return_value=False), \
            patch.object(socket.socket, 'connect', no_network), patch.object(socket.socket, 'connect_ex', no_network), \
            patch.object(socket, 'create_connection', no_network):
        import_seconds = None
        if args.full_service:
            started = time.perf_counter()
            import backend.api  # noqa: F401 - timing the import is the point
            import litellm  # noqa: F401
            import langchain_litellm  # noqa: F401
            import_seconds = time.perf_counter() - started
        report = run()
        if args.full_service:
            report['environment']['versions'].update({name: version(name) for name in ('litellm', 'langchain-litellm', 'fastapi')})
    rss = report['process_peak_rss']['value']
    rss_bytes = rss if sys.platform == 'darwin' else rss * 1024 if sys.platform.startswith('linux') else None
    report['measurement'] = {'full_service_imports': args.full_service, 'service_import_seconds': import_seconds,
                             'network_connections_blocked': True, 'peak_rss_bytes': rss_bytes,
                             'max_rss_mib': args.max_rss_mib,
                             'rss_limit_passed': None if args.max_rss_mib is None else rss_bytes <= args.max_rss_mib * 1024 * 1024,
                             'boundary': 'Process peak RSS; excludes other processes and is not whole-cgroup memory.'}
    print(json.dumps(report, indent=2))
    if report['measurement']['rss_limit_passed'] is False:
        sys.exit(1)
