"""Exercise the real demo pipeline with intercepted provider HTTP and disposable PostgreSQL."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import logging
import os
from pathlib import Path
import re
import resource
import socket
import sys
import threading
import time
from unittest.mock import patch

MIB = 1024 * 1024
QUESTION = 'When is the demo?'
QUOTE = 'The demo is on Friday.'
TRANSCRIPT = ' '.join([QUOTE + ' The team reviewed the plan and agreed to prepare slides.'] * 25)


def container_limits():
    cgroup = Path('/sys/fs/cgroup')
    if not sys.platform.startswith('linux') or not (cgroup / 'memory.max').exists():
        return None
    memory = (cgroup / 'memory.max').read_text().strip()
    cpu, period = (cgroup / 'cpu.max').read_text().split()
    return {'memory_limit_bytes': None if memory == 'max' else int(memory),
            'cpus': None if cpu == 'max' else int(cpu) / int(period)}


def run(dsn, clip, vector_sql, vector_library):
    import httpx
    import psycopg

    if not re.fullmatch(r'postgresql://[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_.~-]+)?@127\.0\.0\.1:[0-9]+/recruiter_demo_test', dsn):
        raise ValueError('Use a direct IPv4 loopback DSN for a fresh database named recruiter_demo_test')
    if not clip.is_file() or not 0 < clip.stat().st_size <= 10 * MIB:
        raise ValueError('Supply a synthetic clip up to 10 MiB')
    route = dict(alias='benchmark', tier='economy', provider='gemini', model='gemini/gemini-3.1-flash-lite',
                 api_key_env='GEMINI_API_KEY', verified_free=True, input_limit_tokens=60000, rpm=100, tpm=1000000, rpd=100)
    stt = dict(provider='groq', model='whisper-large-v3-turbo', keyenv='GROQ_API_KEY', verified_free=True,
               rpm=10, rpd=10, audio_seconds_hour=600, audio_seconds_day=600)
    env = dict(PATH=os.environ['PATH'], PYTHON_DOTENV_DISABLED='1', DATABASE_URL=dsn, DEMO_LIVE_MODE='public',
               ENABLE_PROVIDER_CALLS='true', RATE_LIMIT_SECRET='r' * 48, JOB_TOKEN_SECRET='j' * 48,
               MAX_UPLOAD_MB='10', MAX_MEDIA_SECONDS='120', LLM_ROUTES_JSON=json.dumps([route]),
               STT_PROFILES_JSON=json.dumps([stt]), GEMINI_API_KEY='offline', GROQ_API_KEY='offline',
               ENABLE_GEMINI_EMBEDDINGS='true', GEMINI_EMBEDDINGS_VERIFIED_FREE='true',
               GEMINI_EMBEDDINGS_RPM='100', GEMINI_EMBEDDINGS_TPM='1000000', GEMINI_EMBEDDINGS_RPD='100',
               LITELLM_LOCAL_MODEL_COST_MAP='true', LITELLM_TELEMETRY='false', DO_NOT_TRACK='1')
    with psycopg.connect(dsn) as connection:
        if connection.execute("SELECT to_regclass('public.jobs')").fetchone()[0] is not None:
            raise ValueError('Benchmark requires a fresh disposable database')
        if vector_sql:
            sql = '\n'.join(line for line in vector_sql.read_text().splitlines() if not line.startswith('\\'))
            connection.execute(sql.replace('MODULE_PATHNAME', str(vector_library.resolve(strict=True)).replace("'", "''")))

    overlap = threading.Event()
    rendezvous = threading.Barrier(2, timeout=90)
    counts = {'stt': 0, 'embedding': 0, 'generation': 0}
    count_lock = threading.Lock()
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def loopback_only(connect):
        def checked(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in ('127.0.0.1', '::1'):
                raise AssertionError('Benchmark blocked a non-loopback socket')
            return connect(sock, address)
        return checked

    def fake_http(_transport, request):
        host, path = request.url.host, request.url.path
        if host == 'api.groq.com' and path == '/openai/v1/audio/transcriptions':
            with count_lock:
                counts['stt'] += 1
            return httpx.Response(200, json={'task': 'transcribe', 'language': 'english', 'duration': 120,
                                             'text': TRANSCRIPT, 'segments': [{'text': TRANSCRIPT, 'start': 0, 'end': 1}]})
        if host != 'generativelanguage.googleapis.com':
            raise AssertionError('Benchmark blocked an unexpected HTTP destination')
        payload = json.loads(request.content)
        if path.endswith(':batchEmbedContents'):
            with count_lock:
                counts['embedding'] += 1
            if overlap.is_set():
                rendezvous.wait()
            return httpx.Response(200, json={'embeddings': [
                {'values': [1.0] + [0.0] * 767} for _ in payload['requests']]})
        if not path.endswith(':generateContent'):
            raise AssertionError('Benchmark blocked an unexpected HTTP operation')
        with count_lock:
            counts['generation'] += 1
        request_json = request.content.decode()
        if 'Generate a short professional meeting title' in request_json:
            output = {'title': 'Friday Demo'}
        elif 'Cite every factual claim' in request_json:
            evidence = json.loads(payload['contents'][-1]['parts'][0]['text'])['evidence']
            chunk = next(item for item in evidence if QUOTE in item['text'])
            output = {'answer': QUOTE, 'abstained': False, 'evidence': [{'chunk_id': chunk['chunk_id'], 'quote': QUOTE}]}
        elif 'key_decisions' in request_json:
            output = {'action_items': [], 'key_decisions': ['Schedule the demo for Friday.'], 'open_questions': []}
        else:
            output = {'bullets': [QUOTE]}
        return httpx.Response(200, json={
            'candidates': [{'content': {'role': 'model', 'parts': [{'text': json.dumps(output)}]}, 'finishReason': 'STOP'}],
            'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 15, 'totalTokenCount': 115},
            'modelVersion': 'gemini-3.1-flash-lite',
        })

    stage_metrics = []

    class StageHandler(logging.Handler):
        def emit(self, record):
            match = re.fullmatch(r'metric=stage stage=([a-z_]+) status=(success|failed) elapsed_ms=(\d+)', record.getMessage())
            if match:
                stage_metrics.append({'stage': match[1], 'status': match[2], 'ms': int(match[3])})

    metric_logger = logging.getLogger('uvicorn.error.metrics')
    handler = StageHandler()
    previous_level = metric_logger.level
    metric_logger.addHandler(handler)
    metric_logger.setLevel(logging.INFO)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env, clear=True))
            stack.enter_context(patch('dotenv.load_dotenv', return_value=False))
            stack.enter_context(patch.object(httpx.HTTPTransport, 'handle_request', fake_http))
            stack.enter_context(patch.object(socket.socket, 'connect', loopback_only(original_connect)))
            stack.enter_context(patch.object(socket.socket, 'connect_ex', loopback_only(original_connect_ex)))
            from fastapi.testclient import TestClient

            started = time.perf_counter()
            from backend import api, db
            from langchain_postgres import PGVector
            for logger_name in ('httpx', 'httpx2'):
                stack.enter_context(patch.object(logging.getLogger(logger_name), 'disabled', True))
            if vector_sql:
                stack.enter_context(patch.object(db, 'SCHEMA', db.SCHEMA.replace('CREATE EXTENSION IF NOT EXISTS vector;', '')))
                stack.enter_context(patch.object(PGVector, 'create_vector_extension'))
            primary = stack.enter_context(TestClient(api.app, client=('127.0.0.1', 31000)))
            startup = time.perf_counter() - started
            other = TestClient(api.app, client=('127.0.0.2', 31000))
            stack.callback(other.close)

            def submit(client):
                t = time.perf_counter()
                with clip.open('rb') as source:
                    created = client.post('/jobs', files={'file': ('fixture.mp4', source, 'video/mp4')},
                                          data={'demo_acknowledged': 'true'})
                created.raise_for_status()
                body = created.json()
                headers = {'Authorization': f"Bearer {body['job_token']}"}
                result = client.get(f"/jobs/{body['job_id']}/result", headers=headers)
                result.raise_for_status()
                assert result.json()['title'] == 'Friday Demo'
                return body['job_id'], headers, time.perf_counter() - t

            job_id, headers, first = submit(primary)
            overlap.set()
            with ThreadPoolExecutor(max_workers=2) as workers:
                second = workers.submit(submit, other)
                t = time.perf_counter()
                answer = primary.post(f'/jobs/{job_id}/chat', headers=headers, json={'question': QUESTION})
                chat = time.perf_counter() - t
                answer.raise_for_status()
                assert not answer.json()['abstained'] and answer.json()['citations'][0]['text'] == QUOTE
                second_job, second_headers, concurrent = second.result()
            for client, identifier, capability in ((primary, job_id, headers), (other, second_job, second_headers)):
                client.delete(f'/jobs/{identifier}', headers=capability).raise_for_status()
            with db.connect() as connection:
                audio_ms = connection.execute('SELECT SUM(duration_ms) AS total FROM audio_attempts').fetchone()['total']
                usage = connection.execute('SELECT COUNT(*) AS attempts, SUM(input_tokens) AS reserved_input, '
                                           'SUM(output_tokens) AS reserved_output FROM provider_attempts').fetchone()
                usage = {key: int(value) for key, value in usage.items()}
    finally:
        metric_logger.removeHandler(handler)
        metric_logger.setLevel(previous_level)

    peak_path = Path('/sys/fs/cgroup/memory.peak')
    return {
        'scope': 'Synthetic video, real FFmpeg/PostgreSQL/pgvector/FlashRank, intercepted provider HTTP',
        'system': sys.platform, 'clip_bytes': clip.stat().st_size,
        'app_import_and_startup_seconds': startup, 'jobs_completed': 2,
        'first_job_seconds': first, 'overlapping_job_seconds': concurrent, 'overlapping_chat_seconds': chat,
        'stage_metrics': stage_metrics, 'mocked_requests': counts, 'reserved_audio_ms': int(audio_ms),
        'text_ledger': usage,
        'python_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
        'cgroup_peak_bytes': int(peak_path.read_text()) if peak_path.exists() else None,
        'container_limits': container_limits(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('clip', type=Path)
    parser.add_argument('--linux-gate', action='store_true')
    args = parser.parse_args()
    limits = container_limits()
    if args.linux_gate and limits != {'memory_limit_bytes': 512 * MIB, 'cpus': 0.1}:
        parser.error('Linux gate requires a cgroup v2 container with 512 MiB and 0.1 CPU')
    sql, library = os.getenv('PGVECTOR_TEST_SQL_PATH'), os.getenv('TESTPGVECTORLIB')
    if bool(sql) != bool(library):
        parser.error('Supply both local pgvector fixture paths or neither')
    report = run(os.getenv('TEST_DATABASE_URL', ''), args.clip, Path(sql) if sql else None,
                 Path(library) if library else None)
    print(json.dumps(report, indent=2))
    if args.linux_gate and (report['cgroup_peak_bytes'] is None or report['cgroup_peak_bytes'] >= 450 * MIB):
        raise SystemExit('Workload exceeded the release memory threshold')


if __name__ == '__main__':
    main()
