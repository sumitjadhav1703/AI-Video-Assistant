"""Run a loopback-only FastAPI fixture with real media, pgvector, and mock HTTP."""
import json
import os
import re
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
import uvicorn

TRANSCRIPT = 'The operations team will ship the demo on Friday.'


def generation_payload(request):
    messages = json.loads(request.read())['messages']
    system = messages[0]['content']
    if system.startswith('You answer meeting questions'):
        evidence = json.loads(messages[-1]['content'])['evidence'][0]
        content = {'answer': 'The operations team will ship the demo on Friday.',
                   'abstained': False, 'evidence': [
                       {'chunk_id': evidence['chunk_id'], 'quote': TRANSCRIPT}]}
    elif system.startswith('Generate a short'):
        content = {'title': 'Synthetic Release Review'}
    elif system.startswith('Extract meeting action'):
        content = {'action_items': [{'task': 'Ship the demo', 'owner': 'Operations', 'deadline': 'Friday'}],
                   'key_decisions': ['Ship on Friday'], 'open_questions': ['Who monitors the rollout?']}
    else:
        content = {'bullets': ['The operations team owns the Friday release.']}
    return {'id': 'fixture', 'model': 'openai/gpt-oss-20b', 'created': 1,
            'object': 'chat.completion', 'choices': [
                {'index': 0, 'finish_reason': 'stop',
                 'message': {'role': 'assistant', 'content': json.dumps(content)}}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 20, 'total_tokens': 40}}


def mock_http(_transport, request):
    if request.method == 'POST' and request.url.scheme == 'https':
        if request.url.host == 'api.groq.com' and request.url.path == '/openai/v1/chat/completions':
            return httpx.Response(200, json=generation_payload(request))
        if request.url.host == 'api.groq.com' and request.url.path == '/openai/v1/audio/transcriptions':
            return httpx.Response(200, json={'text': TRANSCRIPT, 'language': 'english', 'duration': 2,
                                              'segments': [{'text': TRANSCRIPT, 'start': 0.25, 'end': 1.5}]})
        if request.url.host == 'generativelanguage.googleapis.com' and request.url.path.endswith(':batchEmbedContents'):
            count = len(json.loads(request.read())['requests'])
            return httpx.Response(200, json={'embeddings': [{'values': [1.0] + [0.0] * 767}] * count})
    raise AssertionError('Unexpected outbound HTTP in the browser fixture')


def main(local_vector_files):
    dsn = os.environ['AVA_BROWSER_TEST_DSN']
    settings = urlsplit(dsn)
    if (settings.scheme != 'postgresql' or settings.hostname != '127.0.0.1'
            or settings.path != '/ava_audit_browser' or settings.query or settings.password):
        raise ValueError('Use a disposable loopback database named ava_audit_browser')
    route = dict(alias='fixture-groq', tier='economy', provider='groq', model='groq/openai/gpt-oss-20b',
                 api_key_env='GROQ_API_KEY', verified_free=True, input_limit_tokens=32000,
                 rpm=100, tpm=500000, rpd=1000)
    profile = dict(provider='groq', model='whisper-large-v3-turbo', keyenv='GROQ_API_KEY',
                   verified_free=True, rpm=100, rpd=1000, audio_seconds_hour=5000, audio_seconds_day=5000)
    config = dict(
        PYTHON_DOTENV_DISABLED='1', DATABASE_URL=dsn, ENABLE_PROVIDER_CALLS='true',
        DEMO_LIVE_MODE='public', JOB_TOKEN_SECRET='browser-fixture-job-capability' * 2,
        RATE_LIMIT_SECRET='browser-fixture-rate-limit' * 2, MAX_MEDIA_SECONDS='120',
        FRONTEND_ORIGIN='http://127.0.0.1:55173', LITELLM_LOCAL_MODEL_COST_MAP='True',
        LITELLM_TELEMETRY='false', DO_NOT_TRACK='1',
        GROQ_API_KEY='synthetic-groq-fixture', GEMINI_API_KEY='synthetic-gemini-fixture',
        LLM_ROUTES_JSON=json.dumps([route]), STT_PROFILES_JSON=json.dumps([profile]),
        ENABLE_GEMINI_EMBEDDINGS='true', GEMINI_EMBEDDINGS_VERIFIED_FREE='true',
        GEMINI_EMBEDDINGS_RPM='100', GEMINI_EMBEDDINGS_TPM='500000', GEMINI_EMBEDDINGS_RPD='1000',
    )
    for name in ('PATH', 'RERANK_MODEL_DIR', 'TMPDIR'):
        if os.getenv(name):
            config[name] = os.environ[name]
    # Prevent ambient libpq or provider configuration from reaching any external service.
    with patch.dict(os.environ, config, clear=True), patch.object(httpx.HTTPTransport, 'handle_request', mock_http):
        from backend import api, db
        from langchain_postgres import PGVector

        # Local testing can load an already-built pgvector library without installing it system-wide.
        if local_vector_files:
            sql_path, library_path = local_vector_files
            sql = '\n'.join(line for line in sql_path.read_text().splitlines() if not line.startswith('\\'))
            with db.connect() as conn:
                if conn.execute("SELECT to_regtype('vector') AS type").fetchone()['type'] is None:
                    conn.execute(sql.replace('MODULE_PATHNAME', str(library_path)))
            with patch.object(db, 'SCHEMA', db.SCHEMA.replace('CREATE EXTENSION IF NOT EXISTS vector;', '')), \
                    patch.object(PGVector, 'create_vector_extension'):
                uvicorn.run(api.app, host='127.0.0.1', port=55800, access_log=False)
        else:
            uvicorn.run(api.app, host='127.0.0.1', port=55800, access_log=False)


if __name__ == '__main__':
    sql_path = os.getenv('PGVECTOR_TEST_SQL_PATH')
    library_path = os.getenv('TESTPGVECTORLIB')
    local_vector_files = None
    if sql_path and library_path:
        local_vector_files = Path(sql_path).resolve(strict=True), Path(library_path).resolve(strict=True)
        if not re.fullmatch(r'[/A-Za-z0-9_.-]+', str(local_vector_files[1])):
            raise ValueError('Use a safe local path to the pgvector test library')
    main(local_vector_files)
