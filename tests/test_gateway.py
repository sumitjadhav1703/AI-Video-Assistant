"""Offline gateway contracts: no provider credentials or network needed."""
import json
import os
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from backend.core import llm_gateway as gateway, summarizer, extractor


ROUTE = dict(alias='demo-a', tier='economy', provider='gemini', model='gemini/gemini-flash-latest',
             api_key_env='GEMINI_API_KEY', verified_free=True, input_limit_tokens=20000,
             rpm=10, tpm=50000, rpd=100)
ENV = dict(ENABLE_PROVIDER_CALLS='true', RATE_LIMIT_SECRET='s' * 32,
           LLM_ROUTES_JSON=json.dumps([ROUTE]), GEMINI_API_KEY='offline-placeholder')


class GatewayTests(unittest.TestCase):
    def setUp(self):
        network = patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('Offline tests prohibit network'))
        network.start()
        self.addCleanup(network.stop)

    def test_real_litellm_router_adapter_uses_exact_gemini_route_without_http_retries(self):
        import httpx
        requests = []
        status = [200]
        def handle(transport, request):
            if request.url.host != 'generativelanguage.googleapis.com':
                raise AssertionError('Unexpected offline network path')
            requests.append(request)
            payload = {'candidates': [{'content': {'parts': [{'text': 'Ready'}], 'role': 'model'},
                                      'finishReason': 'STOP', 'index': 0}],
                       'usageMetadata': {'promptTokenCount': 3, 'candidatesTokenCount': 1, 'totalTokenCount': 4},
                       'modelVersion': 'gemini-2.5-flash'}
            if status[0] != 200:
                payload = {'error': {'message': 'Offline provider unavailable', 'code': status[0],
                                     'status': 'RESOURCE_EXHAUSTED' if status[0] == 429 else 'INTERNAL'}}
            return httpx.Response(status[0], json=payload, request=request)
        with patch.dict(os.environ, ENV, clear=True), patch('httpx.HTTPTransport.handle_request', new=handle):
            for model in ('gemini-2.5-flash', 'gemini-3.1-flash-lite'):
                with self.subTest(model=model):
                    route = gateway.Route(**{**ROUTE, 'model': f'gemini/{model}'})
                    result = gateway._invoke_route(route, gateway._messages('Hello'), .3, 12, 128)
                    self.assertEqual(result.content, 'Ready')
                    request = requests[-1]
                    body = json.loads(request.content)
                    self.assertIn(f'/models/{model}:', request.url.path)
                    self.assertEqual(body['generationConfig'].get('maxOutputTokens', body['generationConfig'].get('max_output_tokens')), 128)
                    self.assertEqual(request.extensions['timeout']['read'], 12)
            self.assertEqual(len(requests), 2)
            for failure in (400, 401, 403, 422, 429, 503):
                status[0] = failure
                before = len(requests)
                with self.subTest(status=failure), self.assertRaises(Exception):
                    gateway._invoke_route(route, gateway._messages('Hello'), .3, 12, 128)
                self.assertEqual(len(requests) - before, 1)

    def test_nvidia_rejects_non_allowlisted_model_before_reservation(self):
        route = {**ROUTE, 'provider': 'nvidia_nim', 'model': 'nvidia_nim/meta/llama-3.1-8b-instruct', 'api_key_env': 'NVIDIA_API_KEY'}
        with patch.dict(os.environ, {**ENV, 'LLM_ROUTES_JSON': json.dumps([route]), 'NVIDIA_API_KEY': 'offline'}, clear=True), \
                patch('backend.core.provider_budget.reserve_attempt') as reserve:
            with self.assertRaisesRegex(ValueError, 'Unsupported fixed provider model'):
                gateway.get_llm()
        reserve.assert_not_called()

    def test_compatible_transports_use_fixed_routes_with_one_wire_request(self):
        import httpx

        variants = (
            ('groq', 'groq/openai/gpt-oss-20b', 'https://api.groq.com/openai/v1'),
            ('nvidia_nim', 'nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b', 'https://integrate.api.nvidia.com/v1'),
            ('openrouter', 'openrouter/meta-llama/llama-3.2-3b-instruct:free', 'https://openrouter.ai/api/v1'),
            ('meta', 'meta/muse-spark-1.3', 'https://api.meta.ai/v1'),
        )
        for provider, model, base in variants:
            key = gateway._KEYS[provider]
            route = gateway.Route(**{**ROUTE, 'provider': provider, 'model': model,
                                     'verified_free': provider != 'meta', 'api_key_env': key})
            env = {key: 'correct-key', 'OPENAI_API_KEY': 'wrong-key', 'OPENAI_BASE_URL': 'https://wrong.invalid/v1',
                   'OPENAI_API_BASE': 'https://wrong.invalid/v1', 'OPENAI_ORG_ID': 'wrong-org',
                   'OPENAI_PROJECT_ID': 'wrong-project', 'HTTPS_PROXY': 'http://wrong.invalid:8080'}
            requests = []

            def handle(transport, request):
                requests.append(request)
                self.assertEqual(str(request.url), base + '/chat/completions')
                self.assertEqual(request.headers['authorization'], 'Bearer correct-key')
                self.assertNotIn('openai-organization', request.headers)
                self.assertNotIn('openai-project', request.headers)
                self.assertEqual(request.extensions['timeout']['read'], 12)
                body = json.loads(request.content)
                self.assertEqual(body['model'], model.split('/', 1)[1])
                self.assertEqual(body['max_completion_tokens' if provider == 'meta' else 'max_tokens'], 128)
                if provider == 'openrouter':
                    self.assertEqual(body['provider'], {'allow_fallbacks': False, 'max_price': {'prompt': 0, 'completion': 0, 'request': 0}})
                    self.assertEqual(body['reasoning'], {'enabled': False})
                    self.assertNotIn('models', body)
                if provider == 'nvidia_nim':
                    self.assertFalse(body['chat_template_kwargs']['enable_thinking'])
                if provider == 'meta':
                    self.assertEqual(body['reasoning_effort'], 'minimal')
                if provider == 'groq':
                    self.assertEqual(body['reasoning_effort'], 'low')
                if status == 'timeout':
                    raise httpx.ReadTimeout('offline timeout', request=request)
                if status != 200:
                    return httpx.Response(status, headers={'x-should-retry': 'true', 'retry-after': '17',
                                                          'location': 'https://wrong.invalid/v1'},
                                          json={'error': {'message': 'offline failure'}}, request=request)
                return httpx.Response(200, json={
                    'id': 'offline', 'created': 1, 'object': 'chat.completion', 'model': body['model'],
                    'choices': [{'index': 0, 'finish_reason': 'stop',
                                 'message': {'role': 'assistant', 'content': 'Ready', 'refusal': 'offline marker'}}],
                    'usage': {'prompt_tokens': 3, 'completion_tokens': 1, 'total_tokens': 4},
                }, request=request)

            with patch.dict(os.environ, env, clear=True), patch('httpx.HTTPTransport.handle_request', new=handle):
                status = 200
                with self.assertLogs('openai', level='DEBUG') as logs:
                    result = gateway._invoke_route(route, gateway._messages('private prompt marker'), .3, 12, 128)
                for private in ('private prompt marker', 'correct-key', 'wrong-key'):
                    self.assertNotIn(private, '\n'.join(logs.output))
                self.assertEqual(result.content, 'Ready')
                self.assertEqual(result.additional_kwargs['refusal'], 'offline marker')
                self.assertEqual(result.usage_metadata['total_tokens'], 4)
                self.assertEqual(len(requests), 1)
                for status in (401, 429, 503, 307, 'timeout'):
                    with self.subTest(provider=provider, status=status):
                        before = len(requests)
                        with self.assertRaises(Exception) as caught:
                            gateway._invoke_route(route, gateway._messages('hello'), .3, 12, 128)
                        self.assertEqual(len(requests) - before, 1)
                        self.assertEqual(gateway._transient(caught.exception), status in (429, 503, 'timeout'))
                        if status == 429:
                            self.assertEqual(gateway._retry_after(caught.exception), 17)

    def test_route_order_and_owner_permissions_are_checked_again_on_invoke(self):
        nvidia = {**ROUTE, 'alias': 'nvidia', 'provider': 'nvidia_nim', 'api_key_env': 'NVIDIA_API_KEY',
                  'model': 'nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b'}
        meta = {**ROUTE, 'alias': 'meta', 'provider': 'meta', 'api_key_env': 'META_API_KEY', 'verified_free': False,
                'model': 'meta/muse-spark-1.3', 'input_price_per_million': '1.25', 'output_price_per_million': '4.25'}
        openrouter = {**ROUTE, 'alias': 'openrouter', 'provider': 'openrouter', 'api_key_env': 'OPENROUTER_API_KEY',
                      'model': 'openrouter/meta-llama/llama-3.2-3b-instruct:free'}
        groq = {**ROUTE, 'alias': 'groq', 'provider': 'groq', 'api_key_env': 'GROQ_API_KEY', 'model': 'groq/test'}
        routes = [meta, ROUTE, openrouter, nvidia, groq]
        env = {**ENV, 'LLM_ROUTES_JSON': json.dumps(routes), 'ENABLE_PAID_META': 'true',
               **{route['api_key_env']: 'offline' for route in routes}}
        with patch.dict(os.environ, env, clear=True), patch('backend.core.provider_budget.reserve_attempt') as reserve, \
                patch.object(gateway, '_invoke_route', return_value=AIMessage(content='Ready')):
            with gateway.operation_scope('owner', owner=True, allow_paid=True):
                owner_model = gateway.get_llm()
                self.assertEqual([route.provider for route in owner_model.routes], list(gateway._ORDER))
            with gateway.operation_scope('owner', owner=True):
                self.assertEqual([route.provider for route in gateway.get_llm().routes], list(gateway._ORDER)[:-1])
            with gateway.operation_scope('public'):
                self.assertEqual([route.provider for route in gateway.get_llm().routes], ['groq', 'openrouter', 'gemini'])
                with patch.dict(os.environ, {'GROQ_API_KEY': '', 'OPENROUTER_API_KEY': '', 'GEMINI_API_KEY': ''}):
                    with self.assertRaisesRegex(RuntimeError, 'No eligible'):
                        owner_model.invoke('hello')
        reserve.assert_not_called()

    def test_paid_meta_requires_decimal_strings_before_reserving(self):
        meta = {**ROUTE, 'alias': 'meta', 'provider': 'meta', 'api_key_env': 'META_API_KEY', 'verified_free': False,
                'model': 'meta/muse-spark-1.3', 'input_price_per_million': 1.25, 'output_price_per_million': '4.25'}
        env = {**ENV, 'LLM_ROUTES_JSON': json.dumps([ROUTE, meta]), 'META_API_KEY': 'offline'}
        with patch.dict(os.environ, env, clear=True), patch('backend.core.provider_budget.reserve_attempt') as reserve, \
                gateway.operation_scope('owner', owner=True, allow_paid=True):
            self.assertEqual([route.provider for route in gateway.get_llm().routes], ['gemini'])
            with patch.dict(os.environ, {'ENABLE_PAID_META': 'true'}), self.assertRaisesRegex(ValueError, 'decimal strings'):
                gateway.get_llm()
        reserve.assert_not_called()

    def test_groq_refuses_invalid_configuration_before_reserving(self):
        route = {**ROUTE, 'provider': 'groq', 'model': 'groq/llama-3.3-70b-versatile', 'api_key_env': 'GROQ_API_KEY'}
        for override in ({'model': 'openai/gpt-oss-20b'}, {'model': 'groq/../wrong'}, {'model': 'groq/https://wrong.invalid'},
                         {'api_key_env': 'OPENAI_API_KEY'}, {'api_base': 'https://wrong.invalid'}, {'verified_free': False}):
            with self.subTest(override=override), patch.dict(os.environ, {
                **ENV, 'LLM_ROUTES_JSON': json.dumps([{**route, **override}]), 'GROQ_API_KEY': 'groq-only',
            }, clear=True), patch('backend.core.provider_budget.reserve_attempt') as reserve:
                with self.assertRaises(ValueError):
                    gateway.get_llm()
                reserve.assert_not_called()

    def test_groq_rejects_openai_custom_headers(self):
        route = {**ROUTE, 'provider': 'groq', 'model': 'groq/llama-3.3-70b-versatile', 'api_key_env': 'GROQ_API_KEY'}
        with patch.dict(os.environ, {**ENV, 'LLM_ROUTES_JSON': json.dumps([route]), 'GROQ_API_KEY': 'groq-only',
                                     'OPENAI_CUSTOM_HEADERS': 'Authorization: Bearer wrong-key'}, clear=True), \
                self.assertRaisesRegex(ValueError, 'OPENAI_CUSTOM_HEADERS'):
            gateway.get_llm()

    def test_pipeline_preflight_forecasts_all_attempts_plus_one_chat(self):
        from backend.core.chunks import prepare_documents
        from types import SimpleNamespace
        documents = prepare_documents([{'text': 'Short meeting', 'start_ms': 0, 'end_ms': 1000,
                                        'timing_precision': 'segment'}], 'job-1')
        embedding = SimpleNamespace(alias='embed', provider='gemini', input_limit_tokens=60000, batch_size=100,
                                    rpm=20, tpm=60000, rpd=100)
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.vector_store.available_embedding_routes', return_value=(embedding,)), \
                patch('backend.core.provider_budget.forecast_attempts') as forecast, gateway.operation_scope('job-1'):
            summarizer.preflight_processing('Short meeting', documents)
        attempts = forecast.call_args.args[1]
        stages = forecast.call_args.kwargs['generation_stages']
        self.assertEqual(len(attempts), 2)
        self.assertEqual([stage[2] for stage in stages], [128, 512, 768, 1024, 1024])
        self.assertTrue(all(stage[0][0].model == ROUTE['model'] for stage in stages))

    def test_over_budget_recording_preflight_makes_no_generation_or_embedding_call(self):
        from backend.core.chunks import prepare_documents
        from backend.core.provider_budget import JobBudgetExceeded
        from types import SimpleNamespace
        text = 'x' * 40000
        documents = prepare_documents([{'text': text, 'start_ms': 0, 'end_ms': 1000,
                                        'timing_precision': 'segment'}], 'job-1')
        embedding = SimpleNamespace(alias='embed', provider='gemini', input_limit_tokens=60000, batch_size=100,
                                    rpm=20, tpm=60000, rpd=100)
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.vector_store.available_embedding_routes', return_value=(embedding,)), \
                patch.object(gateway, '_invoke_route') as network, patch('backend.core.provider_budget.forecast_attempts', side_effect=JobBudgetExceeded('forecast')) as forecast, \
                gateway.operation_scope('job-1'), self.assertRaises(JobBudgetExceeded):
            summarizer.preflight_processing(text, documents)
        network.assert_not_called()
        self.assertGreater(max(stage[1] for stage in forecast.call_args.kwargs['generation_stages']), 40000)

    def test_shared_provider_rejects_invalid_other_operation_limits(self):
        from backend.core.provider_budget import provider_limits
        route = gateway.Route(**ROUTE)
        for env in ({'LLM_ROUTES_JSON': 'invalid'}, {'LLM_ROUTES_JSON': '{}'},
                    {'ENABLE_GEMINI_EMBEDDINGS': 'true'},
                    {'LLM_ROUTES_JSON': json.dumps([{**ROUTE, 'rpm': True}])}):
            with self.subTest(env=env), patch.dict(os.environ, {**ENV, **env}, clear=True), self.assertRaises(ValueError):
                provider_limits(route)

    def test_rag_preflight_missing_model_or_ranker_precedes_dense_embedding(self):
        from backend.core import rag_engine
        for dependency in ('get_llm', 'load_ranker'):
            with self.subTest(dependency=dependency), patch.object(rag_engine, 'get_llm'), \
                    patch.object(rag_engine, 'load_ranker'), patch.object(rag_engine, dependency, side_effect=ValueError('Not configured')), \
                    patch.object(rag_engine, 'hybrid_retrieve') as retrieve:
                with self.assertRaises(ValueError):
                    rag_engine._answer_question('question', 'job', 'economy', [], None)
                retrieve.assert_not_called()

    def test_retrieval_preserves_budget_exception_identity(self):
        from backend.core import retrieval
        from backend.core.provider_budget import JobBudgetExceeded
        from backend.usage_limits import LimitExceeded
        from unittest.mock import Mock
        for error in (LimitExceeded(60), JobBudgetExceeded('Lifetime budget exhausted')):
            vector = Mock()
            vector.similarity_search.side_effect = error
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)) as caught:
                retrieval.hybrid_retrieve('question', 'job', [], vector)
            self.assertIs(caught.exception, error)

    def test_shared_provider_uses_lowest_generation_and_embedding_ceiling(self):
        from backend.core.provider_budget import provider_limits
        from types import SimpleNamespace
        gemini = {**ROUTE, 'provider': 'gemini', 'model': 'gemini/gemini-flash-latest', 'api_key_env': 'GEMINI_API_KEY',
                  'rpm': 4, 'tpm': 10000, 'rpd': 30}
        env = {**ENV, 'LLM_ROUTES_JSON': json.dumps([gemini]), 'ENABLE_GEMINI_EMBEDDINGS': 'true',
               'GEMINI_EMBEDDINGS_RPM': '8', 'GEMINI_EMBEDDINGS_TPM': '5000', 'GEMINI_EMBEDDINGS_RPD': '100'}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(provider_limits(SimpleNamespace(provider='gemini', rpm=8, tpm=20000, rpd=100)),
                             (4, 5000, 30))

    def test_safe_selected_route_metadata_and_usage_are_preserved(self):
        response = AIMessage(content='Ready', additional_kwargs={'private': 'do not propagate'},
            response_metadata={'headers': {'secret': 'drop'}},
            usage_metadata={'input_tokens': 3, 'output_tokens': 1, 'total_tokens': 4})
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.provider_budget.reserve_attempt'), \
                patch.object(gateway, '_invoke_route', return_value=response), gateway.operation_scope('job-1'):
            result = gateway.get_llm().invoke('hello')
        self.assertEqual(result.response_metadata, {'alias': 'demo-a', 'provider': 'gemini',
                         'model': 'gemini/gemini-flash-latest', 'tier': 'economy'})
        self.assertEqual(result.usage_metadata['total_tokens'], 4)
        self.assertFalse(result.additional_kwargs)

    def test_task_output_limits_are_reserved_and_cannot_be_unbounded(self):
        with patch.dict(os.environ, ENV, clear=True), \
                patch('backend.core.provider_budget.reserve_attempt') as reserve, \
                patch.object(gateway, '_invoke_route', return_value=AIMessage(content='Ready')), gateway.operation_scope('job-1'):
            gateway.get_llm(max_output_tokens=128).invoke('hello')
            self.assertEqual(reserve.call_args.kwargs['output_tokens'], 128)
            for limit in (0, -1, True, 1025):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    gateway.get_llm(max_output_tokens=limit)

    def test_extraction_combines_findings_in_one_model_request(self):
        data = '{"action_items":[],"key_decisions":["Use Python"],"open_questions":["Who owns release?"]}'
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.provider_budget.reserve_attempt'), \
                patch.object(gateway, '_invoke_route', return_value=AIMessage(content=data)) as network, gateway.operation_scope('job-1'):
            self.assertEqual(extractor.extract_findings('Meeting notes'), {
                'action_items': 'No action items found.', 'key_decisions': '1. Use Python',
                'open_questions': '1. Who owns release?'})
        self.assertEqual(network.call_count, 1)

    def test_attempt_metadata_records_success_and_retains_usage_reservation(self):
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.provider_budget.reserve_attempt', return_value=42), \
                patch('backend.core.provider_budget.record_attempt_result') as record, \
                patch.object(gateway, '_invoke_route', return_value=AIMessage(content='Ready', usage_metadata={
                    'input_tokens': 3, 'output_tokens': 1, 'total_tokens': 4})), gateway.operation_scope('job-1'):
            self.assertEqual(gateway.get_llm().invoke('hello').content, 'Ready')
        self.assertEqual(record.call_args.args[:2], (42, 'success'))
        self.assertEqual(record.call_args.kwargs['input_tokens'], 3)
        self.assertEqual(record.call_args.kwargs['output_tokens'], 1)

    def test_reservation_time_reduces_network_timeout(self):
        seen = []
        def call(route, messages, temperature, timeout, max_output_tokens=1024):
            seen.append(timeout)
            return AIMessage(content='Ready')
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.provider_budget.reserve_attempt'), \
                patch.object(gateway, '_invoke_route', side_effect=call), \
                patch.object(gateway.time, 'monotonic', side_effect=[100, 100, 110, 110, 111]), gateway.operation_scope('job-1'):
            gateway.get_llm().invoke('hello')
        self.assertEqual(seen, [50])

    def test_debug_logging_fails_closed_for_private_content(self):
        from langchain_core.globals import set_debug
        set_debug(True)
        try:
            with patch.dict(os.environ, ENV, clear=True), self.assertRaises(ValueError):
                gateway.get_llm()
        finally:
            set_debug(False)

    def test_no_routes_fails_closed(self):
        with patch.dict(os.environ, {**ENV, 'LLM_ROUTES_JSON': '[]'}, clear=True):
            with self.assertRaises(ValueError):
                gateway.get_llm()

    def test_route_rejects_paid_unknown_and_duplicate_routes(self):
        for routes in ([{**ROUTE, 'verified_free': False}], [{**ROUTE, 'model': 'openai/wrong'}], [{**ROUTE, 'model': 'gemini/gemini-2.5-pro'}],
                       [ROUTE, ROUTE], [{**ROUTE, 'rpm': True}], [{**ROUTE, 'extra': 'unsafe'}], [{**ROUTE, 'provider': []}], [{**ROUTE, 'model': None}]):
            with self.subTest(routes=routes), patch.dict(os.environ, {**ENV, 'LLM_ROUTES_JSON': json.dumps(routes)}, clear=True):
                with self.assertRaises(ValueError):
                    gateway.get_llm()

    def test_invocation_requires_operation_scope_before_network(self):
        with patch.dict(os.environ, ENV, clear=True):
            llm = gateway.get_llm()
            with self.assertRaises(RuntimeError):
                llm.invoke('hello')

    def test_attempt_reserved_before_provider_and_response_is_sanitized(self):
        events = []
        def reserve(*args, **kwargs):
            events.append('reserved')
        def call(*args, **kwargs):
            events.append('network')
            return AIMessage(content='Ready')
        with patch.dict(os.environ, ENV, clear=True), \
                patch('backend.core.provider_budget.reserve_attempt', side_effect=reserve), \
                patch.object(gateway, '_invoke_route', side_effect=call):
            with gateway.operation_scope('job-1'):
                result = gateway.get_llm().invoke('hello')
            self.assertEqual(result.content, 'Ready')
            self.assertEqual(events, ['reserved', 'network'])

    def test_any_provider_error_falls_back_but_never_silently_strong(self):
        groq = {**ROUTE, 'alias': 'groq', 'provider': 'groq', 'model': 'groq/test', 'api_key_env': 'GROQ_API_KEY'}
        routes = [ROUTE, groq, {**ROUTE, 'alias': 'strong', 'tier': 'strong'}]
        env = {**ENV, 'LLM_ROUTES_JSON': json.dumps(routes), 'GROQ_API_KEY': 'offline'}
        for status in (429, 503, 401, 403, 400, 402):
            def call(route, *args):
                if route.provider == 'groq':
                    error = RuntimeError('provider error')
                    error.status_code = status
                    raise error
                return AIMessage(content='Ready')

            with self.subTest(status=status), patch.dict(os.environ, env, clear=True), \
                    patch('backend.core.provider_budget.reserve_attempt') as reserve, \
                    patch('backend.core.provider_budget.record_route_cooldown') as cooldown, \
                    patch.object(gateway, '_invoke_route', side_effect=call), gateway.operation_scope('job-1'):
                model = gateway.get_llm()
                # Every provider error falls back within the tier; the broken route is skipped for the rest of
                # the job, and the strong tier is never used silently.
                self.assertEqual(model.invoke('hello').content, 'Ready')
                self.assertEqual(model.invoke('follow-up').content, 'Ready')
                self.assertEqual([item.args[1].alias for item in reserve.call_args_list], ['groq', 'demo-a', 'demo-a'])
                if status == 429:
                    cooldown.assert_called_once_with(gateway.Route(**groq), 60)
                else:
                    cooldown.assert_not_called()

    def test_route_quota_or_local_context_denial_skips_without_dispatch(self):
        groq = {**ROUTE, 'alias': 'groq', 'provider': 'groq', 'model': 'groq/test', 'api_key_env': 'GROQ_API_KEY'}
        env = {**ENV, 'LLM_ROUTES_JSON': json.dumps([ROUTE, groq]), 'GROQ_API_KEY': 'offline'}
        for denied in (gateway.provider_budget.RouteQuotaExceeded(60), gateway.provider_budget.RequestContextExceeded('too large')):
            with self.subTest(denied=type(denied).__name__), patch.dict(os.environ, env, clear=True), \
                    patch('backend.core.provider_budget.reserve_attempt', side_effect=[denied, None]) as reserve, \
                    patch.object(gateway, '_invoke_route', return_value=AIMessage(content='Ready')) as network, \
                    gateway.operation_scope('job'):
                self.assertEqual(gateway.get_llm().invoke('hello').content, 'Ready')
                self.assertEqual(reserve.call_count, 2)
                self.assertEqual(network.call_count, 1)
                self.assertEqual(network.call_args.args[0].provider, 'gemini')

    def test_all_quota_denials_preserve_shortest_retry_after(self):
        groq = {**ROUTE, 'alias': 'groq', 'provider': 'groq', 'model': 'groq/test', 'api_key_env': 'GROQ_API_KEY'}
        env = {**ENV, 'LLM_ROUTES_JSON': json.dumps([ROUTE, groq]), 'GROQ_API_KEY': 'offline'}
        quota = gateway.provider_budget.RouteQuotaExceeded
        with patch.dict(os.environ, env, clear=True), \
                patch('backend.core.provider_budget.reserve_attempt', side_effect=[quota(60), quota(17)]), \
                patch.object(gateway, '_invoke_route') as network, gateway.operation_scope('job'):
            with self.assertRaises(quota) as caught:
                gateway.get_llm().invoke('hello')
            self.assertEqual(caught.exception.retry_after, 17)
        network.assert_not_called()

    def test_budget_denial_makes_no_network_attempt(self):
        with patch.dict(os.environ, ENV, clear=True), \
                patch('backend.core.provider_budget.reserve_attempt', side_effect=RuntimeError('budget exhausted')), \
                patch.object(gateway, '_invoke_route') as network:
            with gateway.operation_scope('job-1'), self.assertRaises(RuntimeError):
                gateway.get_llm().invoke('hello')
            network.assert_not_called()

    def test_tracing_configuration_fails_before_provider(self):
        with patch.dict(os.environ, {**ENV, 'LANGSMITH_TRACING': 'true'}, clear=True):
            with self.assertRaises(ValueError):
                gateway.get_llm()

    def test_text_sanitized_before_dispatch_and_before_reuse(self):
        delivered = []
        def call(route, messages, *args):
            delivered.extend(message.content for message in messages)
            return AIMessage(content='Email output@example.com')
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.provider_budget.reserve_attempt'), \
                patch.object(gateway, '_invoke_route', side_effect=call), gateway.operation_scope('job-1'):
            result = gateway.get_llm().invoke('Email input@example.com')
        self.assertNotIn('input@example.com', ' '.join(delivered))
        self.assertNotIn('output@example.com', result.content)

    def test_request_options_and_callback_handlers_cannot_bypass_review(self):
        from langchain_core.callbacks import CallbackManager, BaseCallbackHandler
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.provider_budget.reserve_attempt') as reserve, \
                gateway.operation_scope('job-1'):
            for options in ({'max_tokens': 100000}, {'config': {'callbacks': [BaseCallbackHandler()]}},
                            {'config': {'callbacks': CallbackManager([BaseCallbackHandler()])}}):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    gateway.get_llm().invoke('hello', **options)
        reserve.assert_not_called()

    def test_plain_lcel_chain_with_no_handlers_still_works(self):
        from langchain_core.prompts import ChatPromptTemplate
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.provider_budget.reserve_attempt'), \
                patch.object(gateway, '_invoke_route', return_value=AIMessage(content='Ready')), gateway.operation_scope('job-1'):
            chain = ChatPromptTemplate.from_template('{text}') | gateway.get_llm()
            self.assertEqual(chain.invoke({'text': 'hello'}).content, 'Ready')

    def test_refusal_metadata_is_rejected_without_fallback(self):
        routes = [ROUTE]
        with patch.dict(os.environ, {**ENV, 'LLM_ROUTES_JSON': json.dumps(routes), 'GEMINI_API_KEY': 'test'}, clear=True), \
                patch('backend.core.provider_budget.reserve_attempt'), \
                patch.object(gateway, '_invoke_route', return_value=AIMessage(content='Refused', additional_kwargs={'refusal': 'blocked'})) as network, \
                gateway.operation_scope('job-1'), self.assertRaises(RuntimeError):
            gateway.get_llm().invoke('hello')
        self.assertEqual(network.call_count, 1)

    def test_structured_summary_title_and_findings_preserve_public_text(self):
        findings = '{"action_items":[{"task":"Ship","owner":"Ana","deadline":"Friday"}],"key_decisions":["Use Python"],"open_questions":[]}'
        responses = [AIMessage(content='{"bullets":["First summary"]}'),
                     AIMessage(content='{"bullets":["Final summary"]}'),
                     AIMessage(content='{"title":"Team Planning"}'),
                     AIMessage(content=findings), AIMessage(content=findings), AIMessage(content=findings)]
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.provider_budget.reserve_attempt'), \
                patch.object(gateway, '_invoke_route', side_effect=responses), gateway.operation_scope('job-1'):
            self.assertEqual(summarizer.summarize('Planning notes'), '- Final summary')
            self.assertEqual(summarizer.generate_title('Planning notes'), 'Team Planning')
            self.assertEqual(extractor.extract_action_items('Planning notes'),
                             '1. Task: Ship\n   Owner: Ana\n   Deadline: Friday')
            self.assertEqual(extractor.extract_key_decisions('Planning notes'), '1. Use Python')
            self.assertEqual(extractor.extract_questions('Planning notes'), 'No open questions found.')

    def test_invalid_structured_output_with_no_other_route_fails_after_one_call(self):
        with patch.dict(os.environ, ENV, clear=True), patch('backend.core.provider_budget.reserve_attempt'), \
                patch('backend.core.provider_budget.record_attempt_result'), \
                patch.object(gateway, '_invoke_route', return_value=AIMessage(content='free text')) as network, \
                gateway.operation_scope('job-1'), self.assertRaisesRegex(RuntimeError, 'No eligible'):
            summarizer.generate_title('Planning notes')
        self.assertEqual(network.call_count, 1)

    def test_invalid_or_truncated_output_falls_back_to_the_next_route(self):
        groq = {**ROUTE, 'alias': 'groq-a', 'provider': 'groq', 'api_key_env': 'GROQ_API_KEY', 'model': 'groq/openai/gpt-oss-20b'}
        env = {**ENV, 'LLM_ROUTES_JSON': json.dumps([groq, ROUTE]), 'GROQ_API_KEY': 'offline'}
        for bad in ('Here is the JSON', '', '{"title": "one two three four five six seven eight nine"}'):
            replies = [AIMessage(content=bad), AIMessage(content='Sure: {"title": "Pilot launch plan"} done')]
            with patch.dict(os.environ, env, clear=True), patch('backend.core.provider_budget.reserve_attempt', return_value=1), \
                    patch('backend.core.provider_budget.record_attempt_result') as record, \
                    patch.object(gateway, '_invoke_route', side_effect=replies) as network, gateway.operation_scope('job-1'):
                self.assertEqual(summarizer.generate_title('Planning notes'), 'Pilot launch plan')
            self.assertEqual([call.args[0].alias for call in network.call_args_list], ['groq-a', 'demo-a'])
            self.assertEqual(record.call_args_list[0].args[1], 'failed')

    def test_meta_reserves_and_requests_its_minimum_output(self):
        meta = gateway.Route(**{**ROUTE, 'provider': 'meta', 'api_key_env': 'META_API_KEY', 'verified_free': False,
                                'model': 'meta/muse-spark-1.3', 'input_price_per_million': '1.25',
                                'output_price_per_million': '4.25'})
        chat = gateway.GuardedChat([meta, gateway.Route(**ROUTE)], 0.3, 128)
        self.assertEqual([chat._output_cap(route) for route in chat.routes], [512, 128])

    def test_json_is_recovered_from_fences_and_prose(self):
        for raw in ('```json\n{"a": 1}\n```', 'Here is the JSON: {"a": 1} Hope it helps', '  {"a": 1}  ', '```\n{"a": 1}\n```'):
            self.assertEqual(json.loads(gateway.strip_json_fence(raw)), {'a': 1})
        self.assertEqual(gateway.strip_json_fence('no json here'), 'no json here')

    def test_operation_scope_resets_after_exit(self):
        with patch.dict(os.environ, ENV, clear=True):
            with gateway.operation_scope('job-1'):
                pass
            with self.assertRaises(RuntimeError):
                gateway.get_llm().invoke('hello')

    def _task_routes(self):
        groq = {**ROUTE, 'alias': 'groq-a', 'provider': 'groq', 'api_key_env': 'GROQ_API_KEY', 'model': 'groq/openai/gpt-oss-20b'}
        flash = {**ROUTE, 'alias': 'gemini-b'}
        openrouter = {**ROUTE, 'alias': 'or-a', 'provider': 'openrouter', 'api_key_env': 'OPENROUTER_API_KEY',
                      'model': 'openrouter/nvidia/nemotron-3.5-lightning:free'}
        nvidia = {**ROUTE, 'alias': 'nv-a', 'provider': 'nvidia_nim', 'api_key_env': 'NVIDIA_API_KEY',
                  'model': 'nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b'}
        meta = {**ROUTE, 'alias': 'meta-a', 'provider': 'meta', 'api_key_env': 'META_API_KEY', 'verified_free': False,
                'model': 'meta/muse-spark-1.3', 'input_price_per_million': '1.25', 'output_price_per_million': '4.25'}
        routes = [groq, ROUTE, flash, openrouter, nvidia, meta]
        return {**ENV, 'LLM_ROUTES_JSON': json.dumps(routes), **{r['api_key_env']: 'offline' for r in routes}}

    def test_task_order_prefers_configured_aliases_and_keeps_every_route_as_fallback(self):
        env = {**self._task_routes(), 'ENABLE_PAID_META': 'true', 'ENABLE_PUBLIC_PAID_FALLBACK': 'true',
               'ENABLE_NVIDIA_PUBLIC': 'true',
               'LLM_TASK_ROUTES_JSON': json.dumps({'chat': ['meta-a', 'gemini-b', 'or-a'], 'title': ['nv-a']})}
        with patch.dict(os.environ, env, clear=True), gateway.operation_scope('public'):
            # Paid Meta stays last even when a task lists it first; both Gemini models stay in the chain.
            self.assertEqual([r.alias for r in gateway.get_llm(task='chat').routes],
                             ['gemini-b', 'or-a', 'groq-a', 'nv-a', 'demo-a', 'meta-a'])
            self.assertEqual([r.alias for r in gateway.get_llm(task='title').routes],
                             ['nv-a', 'groq-a', 'or-a', 'demo-a', 'gemini-b', 'meta-a'])
            self.assertEqual([r.alias for r in gateway.get_llm(task='extract').routes],
                             ['groq-a', 'nv-a', 'or-a', 'demo-a', 'gemini-b', 'meta-a'])
            with self.assertRaisesRegex(ValueError, 'Unsupported generation task'):
                gateway.get_llm(task='poem')

    def test_public_paid_and_nvidia_routes_require_explicit_flags(self):
        with patch.dict(os.environ, {**self._task_routes(), 'ENABLE_PAID_META': 'true'}, clear=True), \
                gateway.operation_scope('public'):
            self.assertEqual([r.provider for r in gateway.get_llm().routes], ['groq', 'openrouter', 'gemini', 'gemini'])
        with patch.dict(os.environ, {**self._task_routes(), 'ENABLE_PUBLIC_PAID_FALLBACK': 'true'}, clear=True), \
                gateway.operation_scope('public'):
            self.assertNotIn('meta', [r.provider for r in gateway.get_llm().routes])

    def test_task_mapping_rejects_unknown_tasks_and_aliases(self):
        for mapping in ({'poem': ['groq-a']}, {'chat': ['missing']}, {'chat': ['groq-a', 'groq-a']}, ['groq-a']):
            with patch.dict(os.environ, {**self._task_routes(), 'LLM_TASK_ROUTES_JSON': json.dumps(mapping)}, clear=True), \
                    gateway.operation_scope('public'):
                with self.assertRaisesRegex(ValueError, 'LLM_TASK_ROUTES_JSON'):
                    gateway.get_llm(task='chat')

    def test_gemini_requests_native_json_mode(self):
        captured = {}

        class FakeRouter:
            def __init__(self, **_kwargs):
                pass

            def completion(self, **options):
                captured.update(options)
                raise RuntimeError('offline stop')

        route = gateway.Route(**ROUTE)
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'offline'}, clear=True), \
                patch.object(gateway.private_litellm(), 'Router', FakeRouter):
            with self.assertRaisesRegex(RuntimeError, 'offline stop'):
                gateway._invoke_route(route, [gateway.HumanMessage(content='hi')], 0, 5, 64)
        self.assertEqual(captured['response_format'], {'type': 'json_object'})

    def test_openrouter_requires_free_model(self):
        route = {**ROUTE, 'provider': 'openrouter', 'api_key_env': 'OPENROUTER_API_KEY', 'model': 'openrouter/openai/gpt-4o'}
        with patch.dict(os.environ, {**ENV, 'LLM_ROUTES_JSON': json.dumps([route]), 'OPENROUTER_API_KEY': 'offline'}, clear=True):
            with self.assertRaisesRegex(ValueError, ':free model'):
                gateway.get_llm()

    def test_structured_call_accepts_markdown_fenced_json(self):
        class FakeLLM:
            def __init__(self, content):
                self.content = content

            def with_validator(self, validate):
                self.validate = validate
                return self

            def invoke(self, _messages):
                return AIMessage(content=self.content)

        fenced = '```json\n{\n  "title": "Generative AI Overview"\n}\n```'
        with patch.object(gateway, 'assert_private_runtime'), \
                patch.object(gateway, 'get_llm', return_value=FakeLLM(fenced)):
            self.assertEqual(gateway.structured_call('p', 't', summarizer.Title).title, 'Generative AI Overview')
        with patch.object(gateway, 'assert_private_runtime'), \
                patch.object(gateway, 'get_llm', return_value=FakeLLM('```json\n{"title": 1}\n```')):
            with self.assertRaisesRegex(ValueError, 'invalid structured output'):
                gateway.structured_call('p', 't', summarizer.Title)


if __name__ == '__main__':
    unittest.main()
