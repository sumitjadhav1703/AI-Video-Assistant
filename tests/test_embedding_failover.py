import json
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from sqlalchemy import create_engine

from backend import db
from backend.core import embedding_routes, provider_budget, vector_store
from backend.core.chunks import prepare_documents
from backend.core.llm_gateway import operation_scope


def route_config(route_id):
    return {'id': route_id, 'verified_free': True, 'rpm': 10, 'tpm': 60000, 'rpd': 50}


def openrouter_response(count):
    model, dimension = embedding_routes.EMBEDDING_SPACES['openrouter-nemotron']
    return httpx.Response(200, json={'object': 'list', 'model': model, 'data': [
        {'object': 'embedding', 'index': index, 'embedding': [1.0] + [0.0] * (dimension - 1)}
        for index in reversed(range(count))
    ], 'usage': {'prompt_tokens': count, 'total_tokens': count}})


def gemini_response(count):
    return httpx.Response(200, json={'embeddings': [
        {'values': [0.0, 1.0] + [0.0] * 766} for _ in range(count)
    ]})


def intercept_provider(handler):
    return patch.object(httpx.HTTPTransport, 'handle_request', lambda _, request: handler(request))


class EmbeddingFailoverTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 'x' * 32,
            'OPENROUTER_API_KEY': 'offline', 'GEMINI_API_KEY': 'offline',
            'NVIDIA_API_KEY': 'offline',
            'EMBEDDING_ROUTES_JSON': json.dumps([route_config(route_id) for route_id in (
                'openrouter-nemotron', 'gemini-embeddings', 'nvidia-nemotron')]),
        }, clear=True))
        self.documents = prepare_documents([
            {'text': 'The release is on Friday.', 'start_ms': 0, 'end_ms': 500,
             'timing_precision': 'segment'},
        ], 'job')

    def test_chat_uses_persisted_route_even_with_a_different_first_route(self):
        for saved_route in ('gemini-embeddings', None):
            with self.subTest(saved_route=saved_route), operation_scope('job'), \
                    patch.object(vector_store.db, 'get_job', return_value={
                        'retrieval_version': 'hybrid-v1', 'embedding_route': saved_route,
                        'embedding_model': 'gemini-embedding-001', 'embedding_dimension': 768,
                    }), patch.object(vector_store, 'get_sqlalchemy_url'), patch.object(vector_store, 'PGVector') as store:
                vector_store.load_vector_store('job')
            self.assertEqual(store.call_args.kwargs['embeddings'].route.alias, 'gemini-embeddings')

    def test_http_owner_operation_cannot_use_nvidia_trial(self):
        with operation_scope('job', owner=True):
            self.assertEqual([route.alias for route in vector_store.available_embedding_routes()],
                             ['openrouter-nemotron', 'gemini-embeddings'])
        with operation_scope('job', owner=True, local_owner=True):
            self.assertEqual(vector_store.available_embedding_routes()[-1].alias, 'nvidia-nemotron')

    def test_render_disables_both_nemotron_trial_routes_before_reservation(self):
        with patch.dict(os.environ, {'RENDER': 'true'}), operation_scope('job', owner=True, local_owner=True), \
                patch.object(provider_budget, 'reserve_attempt') as reserve:
            self.assertEqual([route.alias for route in vector_store.available_embedding_routes()], ['gemini-embeddings'])
            for route in embedding_routes.configured_embedding_routes():
                if route.provider in ('openrouter', 'nvidia_nim'):
                    with self.subTest(route=route.alias), self.assertRaises(embedding_routes.EmbeddingRouteUnavailable):
                        embedding_routes.embed_batch(route, ['Private.'])
        reserve.assert_not_called()

    def test_openrouter_private_model_name_is_the_same_model_but_others_are_rejected(self):
        route = embedding_routes.EmbeddingRoute('openrouter-nemotron', 1, 1, 1)
        payload = lambda model: {'model': model, 'data': [{'index': 0, 'embedding': [1.0] + [0.0] * 2047}]}
        self.assertEqual(len(embedding_routes._vectors(route, payload('private/openrouter/nvidia/nemotron-3-embed-1b'), 1)[0]), 2048)
        self.assertEqual(len(embedding_routes._vectors(route, payload('nvidia/nemotron-3-embed-1b:free'), 1)[0]), 2048)
        for other in ('private/openrouter/nvidia/nemotron-3.5-embed-8b', 'openai/text-embedding-3-small', None):
            with self.subTest(other=other), self.assertRaises((ValueError, KeyError, TypeError)):
                embedding_routes._vectors(route, payload(other), 1)

    def test_explicit_route_list_requires_free_entitlement_and_unique_routes(self):
        primary = route_config('openrouter-nemotron')
        fallback = route_config('gemini-embeddings')
        with patch.dict(os.environ, {'EMBEDDING_ROUTES_JSON': json.dumps([fallback, primary])}):
            self.assertEqual([r.alias for r in embedding_routes.configured_embedding_routes()],
                             ['gemini-embeddings', 'openrouter-nemotron'])  # configured order is the failover order
        for invalid in ([primary, primary],
                        [{**primary, 'verified_free': False}], [{**primary, 'rpm': True}],
                        [{**primary, 'model': 'unreviewed-model'}]):
            with self.subTest(invalid=invalid), patch.dict(os.environ, {'EMBEDDING_ROUTES_JSON': json.dumps(invalid)}), \
                    self.assertRaises(ValueError):
                embedding_routes.configured_embedding_routes()

    def test_nvidia_embedding_shares_generation_account_ceiling(self):
        route = embedding_routes.configured_embedding_routes()[-1]
        with patch.dict(os.environ, {'LLM_ROUTES_JSON': json.dumps([
            {'provider': 'nvidia_nim', 'rpm': 3, 'tpm': 60000, 'rpd': 70}
        ])}):
            self.assertEqual(provider_budget.provider_limits(route), (3, 60000, 50))

    def test_quota_after_first_batch_restarts_entire_corpus_and_records_attempts(self):
        transcript = 'Friday release. ' * 500
        documents = prepare_documents([
            {'text': transcript, 'start_ms': 0, 'end_ms': 500, 'timing_precision': 'segment'},
        ], 'job')
        texts = [document.page_content for document in documents]
        self.assertGreater(len(texts), 16)
        received = []

        def provider(request):
            body = json.loads(request.content)
            received.append(request.url.host)
            if request.url.host == 'openrouter.ai':
                self.assertEqual(body['provider'], {'allow_fallbacks': False})
                self.assertEqual(body['model'], embedding_routes.EMBEDDING_SPACES['openrouter-nemotron'][0])
                if len(received) == 1:
                    self.assertEqual(body['input'], ['passage: ' + text for text in texts[:16]])
                    return openrouter_response(16)
                self.assertEqual(body['input'], ['passage: ' + text for text in texts[16:]])
                return httpx.Response(429, headers={'Retry-After': '17'})
            self.assertEqual(request.url.host, 'generativelanguage.googleapis.com')
            self.assertEqual([item['content']['parts'][0]['text'] for item in body['requests']], texts)
            return gemini_response(len(texts))

        with operation_scope('job'), intercept_provider(provider), \
                patch.object(provider_budget, 'forecast_attempts'), \
                patch.object(provider_budget, 'reserve_attempt', side_effect=[1, 2, 3]) as reserve, \
                patch.object(provider_budget, 'record_attempt_result') as record, \
                patch.object(provider_budget, 'record_route_cooldown') as cooldown, \
                patch.object(vector_store, 'get_sqlalchemy_url'), patch.object(vector_store, 'PGVector') as store, \
                patch.object(vector_store.db, 'save_chunks') as save:
            vector_store.build_vector_store(transcript, 'job', documents)

        self.assertEqual(received, ['openrouter.ai', 'openrouter.ai', 'generativelanguage.googleapis.com'])
        self.assertEqual([call.args[1].alias for call in reserve.call_args_list],
                         ['openrouter-nemotron', 'openrouter-nemotron', 'gemini-embeddings'])
        self.assertEqual([call.args[:2] for call in record.call_args_list],
                         [(1, 'success'), (2, 'failed'), (3, 'success')])
        self.assertEqual(cooldown.call_args.args[0].alias, 'openrouter-nemotron')
        self.assertEqual(cooldown.call_args.args[1], 17)
        store.assert_called_once()
        self.assertEqual(store.return_value.add_embeddings.call_args.kwargs['embeddings'],
                         [[0.0, 1.0] + [0.0] * 766] * len(texts))
        save.assert_called_once_with('job', documents, embedding_route='gemini-embeddings')

    def test_pinned_query_timeout_is_retryable_without_switching_provider(self):
        received = []

        def provider(request):
            received.append(request.url.host)
            raise httpx.ReadTimeout('private provider failure', request=request)

        with operation_scope('job'), intercept_provider(provider), \
                patch.object(provider_budget, 'reserve_attempt', return_value=1), \
                patch.object(provider_budget, 'record_attempt_result') as record, \
                self.assertRaises(embedding_routes.EmbeddingRetryable) as failure:
            vector_store.get_embeddings('openrouter-nemotron').embed_query('When is the release?')
        self.assertEqual(received, ['openrouter.ai'])
        self.assertNotIn('private provider failure', str(failure.exception))
        self.assertEqual(record.call_args.args[:2], (1, 'failed'))

    def test_malformed_vectors_are_never_published_or_retried(self):
        response = httpx.Response(200, json={
            'object': 'list',
            'model': embedding_routes.EMBEDDING_SPACES['openrouter-nemotron'][0],
            'data': [{'object': 'embedding', 'index': 0, 'embedding': [1.0]}],
            'usage': {'prompt_tokens': 1, 'total_tokens': 1},
        })
        with operation_scope('job'), \
                intercept_provider(lambda _: response), \
                patch.object(provider_budget, 'forecast_attempts'), \
                patch.object(provider_budget, 'reserve_attempt', return_value=1) as reserve, \
                patch.object(provider_budget, 'record_attempt_result') as record, \
                patch.object(vector_store, 'PGVector') as store, patch.object(vector_store.db, 'save_chunks') as save, \
                self.assertRaises(embedding_routes.EmbeddingRouteUnavailable):
            vector_store.build_vector_store(self.documents[0].page_content, 'job', self.documents)
        reserve.assert_called_once()
        self.assertEqual(record.call_args.args[:2], (1, 'failed'))
        store.assert_not_called()
        save.assert_not_called()

    def test_cloudflare_document_and_query_request_contract(self):
        route_id = 'cloudflare-qwen'
        model, dimension = embedding_routes.EMBEDDING_SPACES[route_id]
        account = 'a' * 32
        vector = [1.0] + [0.0] * (dimension - 1)
        bodies = []

        def provider(request):
            self.assertEqual(str(request.url), f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}')
            self.assertEqual(request.headers['Authorization'], 'Bearer offline-cloudflare')
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={'success': True, 'result': {
                'shape': [1, dimension], 'data': [vector],
            }})

        with patch.dict(os.environ, {
            'CLOUDFLARE_ACCOUNT_ID': account, 'CLOUDFLARE_WORKERS_AI_TOKEN': 'offline-cloudflare',
            'EMBEDDING_ROUTES_JSON': json.dumps([route_config(route_id)]),
        }), operation_scope('job'), intercept_provider(provider), \
                patch.object(provider_budget, 'reserve_attempt', side_effect=[1, 2]) as reserve, \
                patch.object(provider_budget, 'record_attempt_result') as record:
            embeddings = vector_store.get_embeddings(route_id)
            self.assertEqual(embeddings.embed_documents(['Friday.']), [vector])
            self.assertEqual(embeddings.embed_query('When?'), vector)

        self.assertEqual(bodies[0], {'documents': ['Friday.']})
        self.assertEqual(bodies[1]['queries'], ['When?'])
        self.assertIn('retrieve', bodies[1]['instruction'])
        self.assertTrue(all(call.args[1].alias == route_id for call in reserve.call_args_list))
        self.assertEqual([call.args[:2] for call in record.call_args_list], [(1, 'success'), (2, 'success')])

    def test_nvidia_trial_wire_access_requires_local_owner(self):
        route_id = 'nvidia-nemotron'
        model, dimension = embedding_routes.EMBEDDING_SPACES[route_id]
        vector = [1.0] + [0.0] * (dimension - 1)
        bodies = []

        def provider(request):
            self.assertEqual(str(request.url), 'https://integrate.api.nvidia.com/v1/embeddings')
            self.assertEqual(request.headers['Authorization'], 'Bearer offline')
            body = json.loads(request.content)
            self.assertEqual(body['model'], model)
            self.assertEqual(body['truncate'], 'NONE')
            bodies.append(body)
            return httpx.Response(200, json={'model': model, 'data': [{'index': 0, 'embedding': vector}]})

        route = embedding_routes.configured_embedding_routes()[-1]
        with intercept_provider(provider), patch.object(provider_budget, 'reserve_attempt', side_effect=[1, 2]) as reserve, \
                patch.object(provider_budget, 'record_attempt_result') as record:
            with operation_scope('job', owner=True), self.assertRaises(embedding_routes.EmbeddingRouteUnavailable):
                embedding_routes.embed_batch(route, ['Private.'])
            reserve.assert_not_called()
            with operation_scope('job', owner=True, local_owner=True):
                embeddings = vector_store.get_embeddings(route_id)
                self.assertEqual(embeddings.embed_documents(['Friday.']), [vector])
                self.assertEqual(embeddings.embed_query('When?'), vector)
        self.assertEqual([(body['input_type'], body['input']) for body in bodies],
                         [('passage', ['Friday.']), ('query', ['When?'])])
        self.assertTrue(all(call.args[1].alias == route_id for call in reserve.call_args_list))
        self.assertEqual([call.args[:2] for call in record.call_args_list], [(1, 'success'), (2, 'success')])


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL with pgvector')
class EmbeddingPersistenceTests(unittest.TestCase):
    def test_fallback_job_reopens_in_persisted_space_and_deletion_keeps_attempts(self):
        dsn = os.environ['TEST_DATABASE_URL']
        connection_options = conninfo_to_dict(dsn)
        loopback = ('localhost', '127.0.0.1', '::1')
        if connection_options.get('host') not in loopback or connection_options.get('hostaddr', '127.0.0.1') not in loopback:
            raise ValueError('Tests refuse non-loopback databases')
        schema = 'test_embedding_' + uuid.uuid4().hex
        options = f'-c search_path={schema},public'
        vector_sql = os.getenv('PGVECTOR_TEST_SQL_PATH')
        vector_library = os.getenv('TESTPGVECTORLIB')
        if bool(vector_sql) != bool(vector_library):
            raise ValueError('Supply both local pgvector fixture paths or neither')

        def drop_schema():
            with psycopg.connect(dsn) as conn:
                conn.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')

        self.addCleanup(drop_schema)
        with psycopg.connect(dsn, options=options) as conn:
            conn.execute(f'CREATE SCHEMA {schema}')
            if vector_sql:
                script = '\n'.join(line for line in Path(vector_sql).read_text().splitlines() if not line.startswith('\\'))
                library = str(Path(vector_library).resolve(strict=True)).replace("'", "''")
                conn.execute(script.replace('MODULE_PATHNAME', library))
            else:
                conn.execute('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')
        engine = create_engine(dsn.replace('postgresql://', 'postgresql+psycopg://', 1),
                               connect_args={'options': options})
        self.addCleanup(engine.dispose)

        job_id = 'fallback-job'
        transcript = 'The release is on Friday.'
        documents = prepare_documents([
            {'text': transcript, 'start_ms': 0, 'end_ms': 500, 'timing_precision': 'segment'},
        ], job_id)
        received = []

        def provider(request):
            received.append(request.url.host)
            if request.url.host == 'openrouter.ai':
                return httpx.Response(503)
            self.assertEqual(request.url.host, 'generativelanguage.googleapis.com')
            body = json.loads(request.content)
            self.assertEqual(body['requests'][0]['taskType'],
                             'RETRIEVAL_DOCUMENT' if len(received) == 2 else 'RETRIEVAL_QUERY')
            return gemini_response(len(body['requests']))

        with patch.dict(os.environ, {
            'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 'x' * 32,
            'OPENROUTER_API_KEY': 'offline', 'GEMINI_API_KEY': 'offline',
            'EMBEDDING_ROUTES_JSON': json.dumps([route_config('openrouter-nemotron'),
                                                 route_config('gemini-embeddings')]),
        }, clear=True), operation_scope(job_id), \
                patch.object(db, 'connect', side_effect=lambda: psycopg.connect(dsn, options=options, row_factory=dict_row)), \
                patch.object(db, 'SCHEMA', db.SCHEMA.replace('CREATE EXTENSION IF NOT EXISTS vector;', '')), \
                patch.object(vector_store, 'get_sqlalchemy_url', return_value=engine), \
                patch.object(vector_store.PGVector, 'create_vector_extension'), \
                intercept_provider(provider):
            db.init_db()
            db.create_job(job_id, 'english')
            vector_store.build_vector_store(transcript, job_id, documents)
            saved = db.get_job(job_id)
            self.assertEqual(saved['embedding_route'], 'gemini-embeddings')
            self.assertEqual((saved['embedding_model'], saved['embedding_dimension']), ('gemini-embedding-001', 768))
            self.assertEqual([chunk.id for chunk in db.load_chunks(job_id)], [documents[0].id])
            reopened = vector_store.load_vector_store(job_id)
            self.assertEqual([doc.id for doc in reopened.similarity_search('When is the release?')], [documents[0].id])
            self.assertEqual(received, ['openrouter.ai', 'generativelanguage.googleapis.com',
                                        'generativelanguage.googleapis.com'])
            with db.connect() as conn:
                conn.execute("UPDATE jobs SET status='done' WHERE id=%s", (job_id,))
            db.delete_job(job_id)
            self.assertIsNone(db.get_job(job_id))
            self.assertEqual(db.load_chunks(job_id), [])
            with db.connect() as conn:
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM langchain_pg_embedding').fetchone()['n'], 0)
                attempts = conn.execute('SELECT route_alias, status FROM provider_attempts ORDER BY id').fetchall()
            self.assertEqual([(row['route_alias'], row['status']) for row in attempts],
                             [('openrouter-nemotron', 'failed'), ('gemini-embeddings', 'success'),
                              ('gemini-embeddings', 'success')])
