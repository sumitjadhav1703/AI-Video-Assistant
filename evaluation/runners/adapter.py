"""Narrow evaluation adapter over the EXISTING application. Production code is not modified.

Instrumentation is test-only and behaviour-preserving:
  * a spy wraps llm_gateway._invoke_route to record provider/model/latency/raw output per attempt;
  * a logging handler reads the app's own telemetry stage timings;
  * query embeddings are fetched in one batched request (same route, same request shape) and served
    from a cache to RouteEmbeddings.embed_query, so 45 questions cost 1 embedding request, not 45;
  * the per-job lifetime budget (24 attempts / 60k in / 12k out) is enforced per question instead of
    across all 45 questions on the one evaluation job, exactly as if each question were its own session.
"""
import hashlib
import json
import logging
import re
import subprocess
import time
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from datetime import datetime, timezone
from unittest.mock import patch

from evaluation import config
from evaluation.dataset import build_chunks

_STAGE = re.compile(r'metric=stage stage=(\w+) status=(\w+) elapsed_ms=(\d+)')
_BASELINE = ContextVar('eval_job_budget_baseline', default=None)


def git_sha():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=config.ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class StageTimer(logging.Handler):
    """Collects the app's own `metric=stage` telemetry lines."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.stages = []

    def emit(self, record):
        match = _STAGE.search(record.getMessage())
        if match:
            self.stages.append({'stage': match[1], 'status': match[2], 'elapsed_ms': int(match[3])})


@contextmanager
def capture_stages():
    logger = logging.getLogger('uvicorn.error.metrics')
    handler, level = StageTimer(), logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


@contextmanager
def spy_generation(calls):
    """Record every generation attempt without changing it."""
    from backend.core import llm_gateway
    original = llm_gateway._invoke_route

    def spy(route, messages, *args, **kwargs):
        started = time.perf_counter()
        entry = {'alias': route.alias, 'provider': route.provider, 'model': route.model}
        try:
            message = original(route, messages, *args, **kwargs)
        except Exception as error:
            entry.update(ok=False, error=type(error).__name__, elapsed_ms=round((time.perf_counter() - started) * 1000))
            calls.append(entry)
            raise
        entry.update(ok=True, elapsed_ms=round((time.perf_counter() - started) * 1000),
                     raw_output=message.content, usage=message.usage_metadata,
                     finish_reason=message.response_metadata.get('finish_reason'))
        calls.append(entry)
        return message

    with patch.object(llm_gateway, '_invoke_route', side_effect=spy):
        yield


@contextmanager
def per_question_job_budget():
    """Apply the app's per-job budget to each question rather than to the cumulative evaluation job."""
    from backend.core import provider_budget
    original = provider_budget._job_usage

    def scoped(cur, job_id):
        used = original(cur, job_id)
        base = _BASELINE.get()
        return {k: used[k] - base[k] for k in used} if base else used

    with patch.object(provider_budget, '_job_usage', side_effect=scoped):
        yield original


def _start_question_budget(original_job_usage, job_id):
    from backend import db
    with db.connect() as conn, conn.cursor() as cur:
        base = dict(original_job_usage(cur, job_id))
    return _BASELINE.set(base)


class QueryEmbeddingCache:
    """Disk cache of query vectors keyed by route, model and sanitized text."""

    def __init__(self, path=config.CACHE_DIR / 'query_embeddings.json'):
        self.path = path
        self.vectors = json.loads(path.read_text()) if path.exists() else {}
        self.batch_requests = []

    @staticmethod
    def key(route, text):
        return hashlib.sha256(f'{route.alias}|{route.model}|query|{text}'.encode()).hexdigest()

    def prefetch(self, route, texts):
        """One embed_batch(query=True) request per route.batch_size missing texts."""
        from backend.core.embedding_routes import embed_batch
        missing = [t for t in dict.fromkeys(texts) if self.key(route, t) not in self.vectors]
        for start in range(0, len(missing), route.batch_size):
            batch = missing[start:start + route.batch_size]
            started = time.perf_counter()
            vectors = embed_batch(route, batch, query=True)
            self.batch_requests.append({'texts': len(batch), 'elapsed_ms': round((time.perf_counter() - started) * 1000)})
            self.vectors.update({self.key(route, t): v for t, v in zip(batch, vectors)})
            self.save()
        return len(missing)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.vectors))

    @contextmanager
    def serve(self, stats):
        from backend.core import vector_store
        original = vector_store.RouteEmbeddings.embed_query
        cache = self

        def embed_query(self_, text):
            vector = cache.vectors.get(cache.key(self_.route, text))
            if vector is not None:
                stats['hits'] += 1
                return vector
            stats['misses'] += 1
            vector = original(self_, text)
            cache.vectors[cache.key(self_.route, text)] = vector
            cache.save()
            return vector

        with patch.object(vector_store.RouteEmbeddings, 'embed_query', embed_query):
            yield


def ensure_job(job_id=build_chunks.JOB_ID):
    from backend import db
    db.init_db()
    if db.get_job(job_id) is None:
        db.create_job(job_id, 'english')
        db.set_step(job_id, 'rag')
    return db.get_job(job_id)


def index(job_id=build_chunks.JOB_ID):
    """Embed and store the source chunks through the app's own build_vector_store. Idempotent."""
    from backend import db
    from backend.core.llm_gateway import operation_scope
    from backend.core.vector_store import build_vector_store
    ensure_job(job_id)
    if db.load_chunks(job_id):
        return {'status': 'already_indexed', 'chunks': len(db.load_chunks(job_id))}
    segments = build_chunks.load_segments()
    documents = build_chunks.build_documents(segments, job_id)
    transcript = build_chunks.transcript_text(segments)
    started = time.perf_counter()
    with capture_stages() as timer, operation_scope(job_id):
        build_vector_store(transcript, job_id, documents=documents)
    job = db.get_job(job_id)
    return {'status': 'indexed', 'chunks': len(documents), 'embedding_route': job['embedding_route'],
            'embedding_model': job['embedding_model'], 'embedding_dimension': job['embedding_dimension'],
            'elapsed_ms': round((time.perf_counter() - started) * 1000), 'stages': timer.stages, 'at': now()}


def verify_index(job_id=build_chunks.JOB_ID):
    """The stored corpus must be byte-identical to the dataset's chunk file."""
    from backend import db
    stored = db.load_chunks(job_id)
    expected = [json.loads(line) for line in build_chunks.CHUNKS_FILE.read_text().splitlines() if line.strip()]
    got = [hashlib.sha256(d.page_content.encode()).hexdigest() for d in stored]
    if got != [r['sha256'] for r in expected]:
        raise RuntimeError('The indexed corpus does not match evaluation/dataset/chunks.jsonl; re-create the eval DB.')
    return stored


def _context_rows(chunk_ids, by_id):
    return [{'chunk_id': c, 'text': by_id[c].page_content, 'start_ms': by_id[c].metadata['start_ms'],
             'end_ms': by_id[c].metadata['end_ms']} for c in chunk_ids if c in by_id]


def warm_up():
    """Local-only warm-up: reranker model load and LiteLLM import. No provider call."""
    from backend.core.llm_gateway import private_litellm
    from backend.core.reranker import load_ranker
    started = time.perf_counter()
    load_ranker()
    private_litellm()
    return round((time.perf_counter() - started) * 1000)


def answer_one(golden, *, job_id, scope, documents, budget_original):
    """Ask one golden through ask_question(load_rag_chain(...)) and capture every stage."""
    from backend.core.guardrails import sanitize_text
    from backend.core.llm_gateway import operation_scope
    from backend.core.rag_engine import ask_question, load_rag_chain
    by_id = {d.metadata['chunk_id']: d for d in documents}
    calls, error, result = [], None, None
    with ExitStack() as stack:
        timer = stack.enter_context(capture_stages())
        stack.enter_context(spy_generation(calls))
        stack.enter_context(operation_scope(job_id, owner=scope == 'owner', allow_paid=False))
        token = _start_question_budget(budget_original, job_id)
        started = time.perf_counter()
        try:
            result = ask_question(load_rag_chain(job_id), golden['question'])
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)[:200]}
        elapsed = round((time.perf_counter() - started) * 1000)
        _BASELINE.reset(token)
    retrieval = (result or {}).get('retrieval') or {}
    from evaluation.metrics.ir import ranks_to_list
    contexts = {
        'final': _context_rows(retrieval.get('chunk_ids', []), by_id),
        'fused': _context_rows([f['chunk_id'] for f in retrieval.get('fusion', [])], by_id),
        'dense_ranking': ranks_to_list(retrieval.get('dense_ranks', {})),
        'sparse_ranking': ranks_to_list(retrieval.get('sparse_ranks', {})),
        'fused_ranking': [f['chunk_id'] for f in retrieval.get('fusion', [])],
        'final_ranking': list(retrieval.get('chunk_ids', [])),
        'reranked_ranking': [s['chunk_id'] for s in (retrieval.get('reranker') or {}).get('scores', [])],
        'reranker': retrieval.get('reranker'),
    }
    return {'golden': golden, 'result': result, 'error': error, 'contexts': contexts,
            'question_sanitized': sanitize_text(golden['question']),
            'calls': calls, 'stages': timer.stages, 'e2e_ms': elapsed, 'scope': scope, 'at': now()}


def answer_all(goldens, *, scope, job_id=build_chunks.JOB_ID, force=False, out_dir=config.RAW_DIR / 'answers',
               cache_path=config.CACHE_DIR / 'query_embeddings.json', progress=print):
    """Answer every golden, resumable: existing per-case files are kept unless force=True."""
    from backend.core.guardrails import sanitize_text
    from backend.core.llm_gateway import operation_scope
    from backend.core.provider_budget import RouteQuotaExceeded
    from backend.core.vector_store import get_embeddings
    from backend import db
    out_dir.mkdir(parents=True, exist_ok=True)
    documents = verify_index(job_id)
    todo = [g for g in goldens if force or not (out_dir / f'{g["id"]}.json').exists()]
    run = {'scope': scope, 'git_sha': git_sha(), 'started': now(), 'warmup_ms': warm_up(), 'cases': [],
           'embedding': {}, 'stopped_early': None}
    if not todo:
        return run
    route = get_embeddings(db.get_job(job_id)['embedding_route']).route
    cache, stats = QueryEmbeddingCache(cache_path), {'hits': 0, 'misses': 0}
    with operation_scope(job_id, owner=scope == 'owner', allow_paid=False):
        fetched = cache.prefetch(route, [sanitize_text(g['question']) for g in todo])
    run['embedding'] = {'route': route.alias, 'model': route.model, 'prefetched': fetched,
                        'batch_requests': cache.batch_requests}
    with cache.serve(stats), per_question_job_budget() as budget_original:
        for number, golden in enumerate(todo, 1):
            case = answer_one(golden, job_id=job_id, scope=scope, documents=documents, budget_original=budget_original)
            case['cold'] = number == 1
            (out_dir / f'{golden["id"]}.json').write_text(json.dumps(case, ensure_ascii=False, indent=1))
            run['cases'].append(golden['id'])
            status = case['error']['type'] if case['error'] else ('abstained' if case['result']['abstained'] else 'answered')
            progress(f'[{number}/{len(todo)}] {golden["id"]}: {status} ({case["e2e_ms"]} ms)')
            if case['error'] and case['error']['type'] in (RouteQuotaExceeded.__name__, 'LimitExceeded', 'RuntimeError'):
                # Daily caps or no eligible route: stop and resume later instead of burning retries.
                (out_dir / f'{golden["id"]}.json').unlink()
                run['stopped_early'] = case['error']
                break
    run['embedding']['cache'] = stats
    run['finished'] = now()
    return run


def load_answers(out_dir=config.RAW_DIR / 'answers'):
    return {p.stem: json.loads(p.read_text()) for p in sorted(out_dir.glob('*.json'))} if out_dir.exists() else {}
