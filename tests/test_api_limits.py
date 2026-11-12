import importlib
import asyncio
import tempfile
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

with patch('dotenv.load_dotenv', return_value=False):
    api = importlib.import_module('backend.api')


class APILimitTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32,
            'DEMO_LIVE_MODE': 'public', 'JOB_TOKEN_SECRET': 'j' * 32,
        }, clear=True)
        self.env.start()
        self.preflight = patch.object(api, 'preflight_pipeline', create=True)
        self.preflight.start()
        self.stt_profile = patch.object(api, 'profile_for_language', create=True)
        self.stt_profile.start()
        self.client = TestClient(api.app, client=('127.0.0.1', 50000))
        self.client.headers['Authorization'] = 'Bearer ' + api._job_token('a' * 32)
        self.job = {'id': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'status': 'done', 'title': 'title'}

    def tearDown(self):
        self.stt_profile.stop()
        self.preflight.stop()
        self.env.stop()

    def test_readiness_checks_database_and_vector_operation(self):
        with patch.object(api.db, 'connect') as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            response = self.client.get('/ready')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'status': 'ok'})
            cursor.execute.assert_called_once()
            self.assertIn('::vector', cursor.execute.call_args.args[0])

    def test_readiness_masks_database_errors_and_liveness_is_independent(self):
        with patch.object(api.db, 'connect', side_effect=RuntimeError('postgresql://secret@host')) as connect:
            with self.assertLogs('backend.api', level='WARNING') as logs:
                response = self.client.get('/ready')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {'detail': api._UNAVAILABLE})
            self.assertNotIn('secret', '\n'.join(logs.output))
            self.assertEqual(self.client.get('/health').status_code, 200)
            connect.assert_called_once()

    def test_authentication_and_invitation_before_parsing_or_preflight(self):
        with patch.dict(os.environ, {'DEMO_LIVE_MODE': 'invited', 'DEMO_INVITE_CODE': 'i' * 32}), patch.object(api, 'preflight_pipeline') as preflight, patch.object(api.db, 'get_job_status') as lookup:
            response = self.client.post('/jobs', content=b'invalid')
            self.assertEqual(response.status_code, 403)
            preflight.assert_not_called()
            for path in ('/jobs/' + 'a' * 32, '/jobs/' + 'a' * 32 + '/result', '/jobs/' + 'a' * 32 + '/chat'):
                response = self.client.request('POST' if path.endswith('/chat') else 'GET', path, content=b'invalid', headers={'Authorization': 'Bearer invalid'})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.headers['cache-control'], 'no-store')
            lookup.assert_not_called()

    def test_job_token_is_bound_and_expires(self):
        for owner, audience in ((False, 'demo'), (True, 'owner')):
            token = api._job_token('a' * 32, owner=owner)
            self.assertEqual(api._job_audience('a' * 32, 'Bearer ' + token), audience)
            self.assertIsNone(api._job_audience('b' * 32, 'Bearer ' + token))
            tampered = token.replace('.owner.', '.') if owner else token.replace('.', '.owner.', 1)
            self.assertIsNone(api._job_audience('a' * 32, 'Bearer ' + tampered))
            with patch.object(api.time, 'time', return_value=int(token.split('.')[0])):
                self.assertIsNone(api._job_audience('a' * 32, 'Bearer ' + token))

    def test_owner_credentials_and_global_switch_fail_closed(self):
        owner = 'e' * 43
        headers = {'X-Owner-Evaluation': owner}
        with patch.object(api.db, 'admit_job') as admit:
            response = self.client.post('/jobs', content=b'invalid', headers=headers)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn(owner, response.text)
            with patch.dict(os.environ, {'OWNER_EVALUATION_TOKEN': owner, 'JOB_TOKEN_SECRET': owner}):
                self.assertEqual(self.client.post('/jobs', content=b'invalid', headers=headers).status_code, 403)
            with patch.dict(os.environ, {'OWNER_EVALUATION_TOKEN': owner, 'ENABLE_PROVIDER_CALLS': 'false'}):
                self.assertEqual(self.client.post('/jobs', content=b'invalid', headers=headers).status_code, 503)
            admit.assert_not_called()

    def test_owner_admission_rejects_non_synthetic_input_and_ambiguous_paid_opt_in(self):
        headers = {'X-Owner-Evaluation': 'e' * 43}
        form = {'demo_acknowledged': 'true'}
        with patch.dict(os.environ, {'OWNER_EVALUATION_TOKEN': 'e' * 43, 'DEMO_LIVE_MODE': 'sample'}), \
                patch.object(api.db, 'admit_job') as admit:
            self.assertEqual(self.client.post('/jobs', data={**form, 'youtube_url': 'https://example.com'}, headers=headers).status_code, 400)
            self.assertEqual(self.client.post('/jobs', data=form, files={'file': ('test.wav', b'bad')}, headers=headers).status_code, 400)
            self.assertEqual(self.client.post('/jobs', data=form, headers={**headers, 'X-Owner-Allow-Paid': 'yes'}).status_code, 400)
            admit.assert_not_called()

    def test_owner_job_artifacts_require_both_credentials_and_chat_keeps_same_budget(self):
        from contextlib import nullcontext

        owner = 'e' * 43
        owner_header = {'X-Owner-Evaluation': owner}
        with patch.dict(os.environ, {'OWNER_EVALUATION_TOKEN': owner, 'DEMO_LIVE_MODE': 'sample'}), \
                patch.object(api.db, 'admit_job', return_value='processing-slot'), \
                patch.object(api, 'run_job') as worker, \
                patch.object(api, 'operation_scope', return_value=nullcontext()) as scope:
            response = self.client.post('/jobs', data={'demo_acknowledged': 'true'}, headers=owner_header)
            self.assertEqual(response.status_code, 200)
            job = response.json()
            worker.assert_called_once_with(job['job_id'], None, reservation_token='processing-slot', owner=True, allow_paid=False)
            scope.assert_called_once_with(job['job_id'], owner=True, allow_paid=False)

            path = f"/jobs/{job['job_id']}"
            job_header = {'Authorization': 'Bearer ' + job['job_token']}
            artifact = dict(status='done', title='synthetic', transcript='test transcript', summary='',
                            action_items='', key_decisions='', open_questions='')
            with patch.object(api.db, 'get_job_status', return_value={'status': 'done', 'step': 'rag', 'error': None}) as status, \
                    patch.object(api.db, 'get_job', return_value=artifact) as result, patch.object(api.db, 'delete_job') as delete, \
                    patch.object(api.db, 'reserve_chat', return_value='chat-slot') as chat, \
                    patch.object(api.db, 'release_slot'), patch.object(api, 'load_rag_chain') as load, \
                    patch.object(api, 'ask_question', return_value={'answer': 'twelve', 'abstained': False, 'citations': []}):
                for method, suffix in [('GET', ''), ('GET', '/result'), ('DELETE', ''), ('POST', '/chat')]:
                    for headers in (job_header, owner_header, {**job_header, 'X-Owner-Evaluation': 'wrong'}):
                        denied = self.client.request(method, path + suffix, headers=headers)
                        self.assertEqual(denied.status_code, 404)
                        self.assertEqual(denied.headers['cache-control'], 'no-store')
                for operation in (status, result, delete, chat, load):
                    operation.assert_not_called()

                headers = {**job_header, **owner_header}
                self.assertEqual(self.client.get(path, headers=headers).status_code, 200)
                result_response = self.client.get(path + '/result', headers=headers)
                self.assertEqual(result_response.status_code, 200)
                self.assertEqual(result_response.json()['transcript'], artifact['transcript'])
                self.assertEqual(result_response.headers['cache-control'], 'no-store')
                self.assertEqual(self.client.post(path + '/chat', json={'question': 'arbitrary'}, headers=headers).status_code, 422)
                chat.assert_not_called()
                response = self.client.post(path + '/chat', json={'question': job['questions'][0], 'tier': 'strong'},
                                            headers={**headers, 'X-Owner-Allow-Paid': 'true'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(chat.call_args.args[0], job['job_id'])
                load.assert_called_once_with(job['job_id'], 'strong')
                self.assertEqual(scope.call_args_list[-1].args, (job['job_id'],))
                self.assertEqual(scope.call_args_list[-1].kwargs, {'owner': True, 'allow_paid': True})

    def test_ordinary_job_cannot_be_elevated(self):
        owner = 'e' * 43
        with patch.dict(os.environ, {'OWNER_EVALUATION_TOKEN': owner}), patch.object(api.db, 'reserve_chat') as chat:
            path = '/jobs/' + 'a' * 32 + '/chat'
            for headers in ({'X-Owner-Evaluation': owner}, {'X-Owner-Allow-Paid': 'true'},
                            {'X-Owner-Evaluation': owner, 'X-Owner-Allow-Paid': 'true'}):
                response = self.client.post(path, json={'question': 'hello', 'tier': 'strong'}, headers=headers)
                self.assertEqual(response.status_code, 403)
            self.assertEqual(self.client.post(path, json={'question': 'hello', 'tier': 'strong'}).status_code, 422)
            chat.assert_not_called()

    def test_default_mode_is_sample(self):
        with patch.dict(os.environ, {'DEMO_LIVE_MODE': 'sample'}):
            self.assertEqual(self.client.get('/demo-mode').json(), {'mode': 'sample'})
            self.assertEqual(self.client.post('/jobs', content=b'invalid').status_code, 403)
            self.assertEqual(self.client.post('/jobs/' + 'a' * 32 + '/chat', content=b'invalid').status_code, 403)
            self.assertEqual(self.client.post('/jobs/' + 'a' * 32 + '/chat', headers={'Authorization': 'Bearer invalid'}, content=b'invalid').status_code, 404)

    def test_disabled_processing_rejects_before_body_read(self):
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'false'}), patch.object(api.db, 'create_job') as create:
            response = self.client.post('/jobs', content=b'not multipart')
        self.assertEqual(response.status_code, 503)
        create.assert_not_called()

    def test_unconfigured_pipeline_rejected_before_job_body_or_admission(self):
        with patch.object(api, 'preflight_pipeline', side_effect=ValueError('missing route')), patch.object(api.db, 'admit_job') as admit:
            response = self.client.post('/jobs', content=b'not multipart')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('missing route', response.text)
        admit.assert_not_called()

    def test_hinglish_is_rejected_before_admission(self):
        with patch.dict(os.environ, {'ENABLE_SARVAM': 'true'}), patch.object(api.db, 'admit_job') as admit:
            response = self.client.post('/jobs', data={'language': 'hinglish', 'demo_acknowledged': 'true'}, files={'file': ('x.wav', b'abc')})
        self.assertEqual(response.status_code, 400)
        admit.assert_not_called()

    def test_chat_rate_limit_is_429_with_retry_after(self):
        from backend.usage_limits import LimitExceeded
        with patch.object(api.db, 'reserve_chat', return_value='owner'), patch.object(api.db, 'release_slot'), patch.object(api, 'load_rag_chain', side_effect=LimitExceeded(45)):
            response = self.client.post('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/chat', json={'question': 'hello'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '45')

    def test_pinned_embedding_unavailability_returns_retryable_503(self):
        from backend.core.embedding_routes import EmbeddingRetryable

        with patch.object(api.db, 'reserve_chat', return_value='owner'), \
                patch.object(api.db, 'release_slot') as release, patch.object(api, 'load_rag_chain'), \
                patch.object(api, 'ask_question', side_effect=EmbeddingRetryable('provider internals')):
            response = self.client.post('/jobs/' + 'a' * 32 + '/chat', json={'question': 'hello'})
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.headers['Retry-After'].isdigit())
        self.assertNotIn('provider internals', response.text)
        release.assert_called_once_with('chat', 'owner')

    def test_job_budget_exhaustion_has_no_retry_after(self):
        from backend.core.provider_budget import JobBudgetExceeded
        with patch.object(api.db, 'reserve_chat', return_value='owner'), patch.object(api.db, 'release_slot'), patch.object(api, 'load_rag_chain', side_effect=JobBudgetExceeded('budget')):
            response = self.client.post('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/chat', json={'question': 'hello'})
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('Retry-After', response.headers)
        self.assertIn('new job', response.json()['detail'].lower())

    def test_invalid_question_rejected_before_provider_or_reservation(self):
        with patch.object(api.db, 'get_job', return_value=self.job), patch.object(api, 'load_rag_chain') as provider:
            for question in ('   ', 'q' * 1001):
                response = self.client.post('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/chat', json={'question': question})
                self.assertIn(response.status_code, (400, 422))
        provider.assert_not_called()

    def test_validation_omits_chat_input_but_identifies_invalid_field(self):
        marker = 'synthetic-private-chat-value'
        with patch.object(api.db, 'reserve_chat') as reserve, patch.object(api, 'load_rag_chain') as provider:
            response = self.client.post('/jobs/' + 'a' * 32 + '/chat', json={'question': [marker]})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(marker, response.text)
        self.assertEqual(response.json()['detail'][0]['loc'], ['body', 'question'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        reserve.assert_not_called()
        provider.assert_not_called()

    def test_non_ascii_cleanup_credentials_are_unauthorized(self):
        with patch.object(api, 'ADMIN_TOKEN', 'a' * 32), patch.object(api.db, 'job_ids_older_than') as lookup:
            client = TestClient(api.app, raise_server_exceptions=False)
            response = client.post('/admin/cleanup', headers=[(b'x-admin-token', bytes([255]))])
        self.assertEqual(response.status_code, 401)
        lookup.assert_not_called()

    def test_cleanup_does_not_report_success_when_a_database_delete_failed(self):
        from backend.usage_limits import JobBusy
        with patch.object(api, 'ADMIN_TOKEN', 'a' * 32), \
                patch.object(api.db, 'job_ids_older_than', return_value=['busy', 'fail', 'ok']), \
                patch.object(api.db, 'delete_job', side_effect=[JobBusy(), RuntimeError('private details'), None]) as delete:
            response = self.client.post('/admin/cleanup', headers={'X-Admin-Token': 'a' * 32})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private details', response.text)
        self.assertEqual([call.args[0] for call in delete.call_args_list], ['busy', 'fail', 'ok'])

    def test_no_untrusted_forwarded_ip_used(self):
        with patch.object(api.db, 'admit_job', return_value='token', create=True) as reserve, patch.object(api, 'run_job', side_effect=lambda job, source, *args, **kwargs: os.remove(source)), patch.object(api.db, 'create_job'):
            response = self.client.post('/jobs', data={'demo_acknowledged': 'true'}, files={'file': ('x.wav', b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')}, headers={'X-Forwarded-For': '8.8.8.8'})
        self.assertEqual(response.status_code, 200)
        from backend.usage_limits import client_key
        self.assertEqual(reserve.call_args.args[2], client_key('127.0.0.1', 's' * 32))

    def test_consent_required_before_job_admission(self):
        with patch.object(api.db, 'admit_job') as admit:
            for data in ({}, {'demo_acknowledged': 'false'}):
                response = self.client.post('/jobs', data=data, files={'file': ('x.wav', b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')})
                self.assertEqual(response.status_code, 422)
            admit.assert_not_called()

    def test_chat_redacts_question_and_returns_citations(self):
        from contextlib import nullcontext
        answer = {'answer': 'yes', 'abstained': False, 'citations': [{'chunk_id': 'abc:000000', 'text': 'yes', 'start_ms': 0, 'end_ms': 1000, 'timing_precision': 'segment'}], 'retrieval': 'hybrid', 'model': 'economy', 'secret': 'hidden'}
        with patch.object(api.db, 'reserve_chat', return_value='owner'), patch.object(api.db, 'release_slot'), patch.object(api, 'operation_scope', return_value=nullcontext()), patch.object(api, 'load_rag_chain') as load, patch.object(api, 'ask_question', return_value=answer) as ask:
            response = self.client.post('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/chat', json={'question': 'Email alice@example.com', 'tier': 'economy'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('alice@example.com', ask.call_args.args[1])
        load.assert_called_once_with('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'economy')
        self.assertEqual(response.json()['citations'][0]['chunk_id'], 'abc:000000')
        self.assertNotIn('secret', response.text)

    def test_legacy_result_redacts_transcript(self):
        job = dict(status='done', title='title', transcript='alice@example.com', summary='', action_items='', key_decisions='', open_questions='')
        with patch.object(api.db, 'get_job', return_value=job):
            response = self.client.get('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/result')
        self.assertNotIn('alice@example.com', response.text)

    def test_database_failure_is_safe_and_no_provider_runs(self):
        with patch.object(api.db, 'get_job', return_value=self.job), patch.object(api.db, 'reserve_chat', side_effect=RuntimeError('secret db host'), create=True), patch.object(api, 'load_rag_chain') as provider:
            response = self.client.post('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/chat', json={'question': 'hello'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.text)
        provider.assert_not_called()

    def test_quota_returns_retry_after(self):
        from backend.usage_limits import LimitExceeded
        with patch.object(api.db, 'get_job', return_value=self.job), patch.object(api.db, 'reserve_chat', side_effect=LimitExceeded(45), create=True), patch.object(api, 'load_rag_chain') as provider:
            response = self.client.post('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/chat', json={'question': 'hello'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '45')
        provider.assert_not_called()

    def test_chat_releases_exact_slot_after_provider_failure(self):
        with patch.object(api.db, 'get_job', return_value=self.job), patch.object(api.db, 'reserve_chat', return_value='owner', create=True), patch.object(api.db, 'release_slot', create=True) as release, patch.object(api, 'load_rag_chain', side_effect=RuntimeError('secret provider response')):
            response = self.client.post('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/chat', json={'question': 'hello'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.text)
        release.assert_called_once_with('chat', 'owner')

    def test_delete_database_failure_has_safe_response(self):
        with patch.object(api.db, 'delete_job', side_effect=RuntimeError('secret')) as delete:
            response = self.client.delete('/jobs/' + 'a' * 32)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.text)
        delete.assert_called_once_with('a' * 32)

    def test_rejects_active_delete(self):
        from backend.usage_limits import JobBusy
        with patch.object(api.db, 'delete_job', side_effect=JobBusy()):
            response = self.client.delete('/jobs/' + 'a' * 32)
        self.assertEqual(response.status_code, 409)

    def test_multipart_overflow_closes_parser_tempfiles(self):
        opened = []
        original = tempfile.SpooledTemporaryFile
        def spool(*args, **kwargs):
            handle = original(*args, **kwargs)
            opened.append(handle)
            return handle
        messages = iter([
            {'type': 'http.request', 'body': b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="x.wav"\r\nContent-Type: audio/wav\r\n\r\n' + b'x' * 100, 'more_body': True},
            {'type': 'http.request', 'body': b'x' * (2 * 1024 * 1024), 'more_body': True},
        ])
        sent = []
        async def receive():
            return next(messages)
        async def send(message):
            sent.append(message)
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST', 'scheme': 'http', 'path': '/jobs', 'raw_path': b'/jobs', 'query_string': b'', 'headers': [(b'content-type', b'multipart/form-data; boundary=boundary')], 'client': ('127.0.0.1', 50000), 'server': ('testserver', 80), 'root_path': ''}
        with patch.dict(os.environ, {'MAX_UPLOAD_MB': '1'}), patch('starlette.formparsers.SpooledTemporaryFile', side_effect=spool):
            asyncio.run(api.app(scope, receive, send))
        self.assertEqual(sent[0]['status'], 413)
        self.assertTrue(opened)
        self.assertTrue(all(handle.closed for handle in opened))

    def test_total_body_length_cap_before_parsing(self):
        response = self.client.post('/jobs', content=b'x', headers={'Content-Length': str(26 * 1024 * 1024)})
        self.assertEqual(response.status_code, 413)

    def test_chunked_body_cap_before_json_parsing(self):
        response = self.client.post('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/chat', content=iter([b'x' * 5000, b'x' * 5000]), headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 413)

    def test_padded_question_uses_trimmed_length(self):
        with patch.object(api.db, 'reserve_chat', return_value='owner'), patch.object(api.db, 'release_slot'), patch.object(api, 'load_rag_chain'), patch.object(api, 'ask_question', return_value={'answer': 'answer', 'abstained': False, 'citations': [], 'retrieval': {}, 'model': {}}) as ask:
            response = self.client.post('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/chat', json={'question': ' ' * 1000 + 'hello'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ask.call_args.args[1], 'hello')

    def test_duplicate_files_rejected_without_reservation(self):
        with patch.object(api.db, 'admit_job') as reserve:
            response = self.client.post('/jobs', data={'demo_acknowledged': 'true'}, files=[('file', ('a.wav', b'a')), ('file', ('b.wav', b'b'))])
        self.assertEqual(response.status_code, 400)
        reserve.assert_not_called()

    def test_empty_upload_releases_slot_and_marks_failed(self):
        with patch.object(api.db, 'admit_job', return_value='owner'), patch.object(api.db, 'release_slot') as release, patch.object(api.db, 'fail_job') as fail, patch.object(api, 'run_job') as worker:
            response = self.client.post('/jobs', data={'demo_acknowledged': 'true'}, files={'file': ('a.wav', b'')})
        self.assertEqual(response.status_code, 400)
        release.assert_called_once_with('processing', 'owner')
        fail.assert_called_once()
        worker.assert_not_called()

    def test_status_poll_uses_narrow_query(self):
        with patch.object(api.db, 'get_job_status', return_value={'status': 'running', 'step': 'audio', 'error': None}, create=True), patch.object(api.db, 'get_job') as full_job:
            response = self.client.get('/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
        self.assertEqual(response.status_code, 200)
        full_job.assert_not_called()

    def test_local_path_and_invalid_language_rejected_before_admission(self):
        with patch.object(api.db, 'admit_job', create=True) as reserve, patch.object(api.db, 'create_job'):
            response = self.client.post('/jobs', data={'youtube_url': '/etc/passwd', 'demo_acknowledged': 'true'})
            self.assertEqual(response.status_code, 400)
            response = self.client.post('/jobs', data={'language': 'invalid'}, files={'file': ('x.wav', b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')})
            self.assertEqual(response.status_code, 422)
        reserve.assert_not_called()


class JobSafetyTests(unittest.TestCase):
    def test_owner_worker_uses_synthetic_text_without_media_or_transcription(self):
        from contextlib import nullcontext
        from backend import jobs

        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32}, clear=True), \
                patch.object(jobs, 'process_input') as media, patch.object(jobs, 'transcribe_segments') as stt, \
                patch.object(jobs.db, 'set_step'), patch.object(jobs.db, 'fail_job') as fail, \
                patch.object(jobs, 'operation_scope', return_value=nullcontext()) as scope, \
                patch.object(jobs, 'preflight_processing') as preflight, patch.object(jobs, 'generate_title', return_value='title'), \
                patch.object(jobs, 'summarize', return_value='summary'), patch.object(jobs, 'extract_findings', return_value={
                    'action_items': '', 'key_decisions': '', 'open_questions': '',
                }), patch.object(jobs, 'build_rag_chain') as index, patch.object(jobs.db, 'finish_job') as finish, \
                patch.object(jobs.db, 'release_slot') as release:
            jobs.run_job('owner-job', None, reservation_token='slot', owner=True, allow_paid=True)
            media.assert_not_called()
            stt.assert_not_called()
            fail.assert_not_called()
            scope.assert_called_once_with('owner-job', owner=True, allow_paid=True, local_owner=False)
            transcript, documents = preflight.call_args.args
            self.assertIn('twelve seats', transcript)
            self.assertTrue(all(document.metadata['timing_precision'] == 'unknown' for document in documents))
            index.assert_called_once_with(transcript, 'owner-job', documents=documents)
            finish.assert_called_once()
            release.assert_called_once_with('processing', 'slot')

    def test_disabled_worker_makes_no_media_calls_and_releases_reservation(self):
        from backend import jobs
        with patch.dict(os.environ, {}, clear=True), patch.object(jobs, 'process_input') as media, patch.object(jobs.db, 'fail_job') as fail, patch.object(jobs.db, 'release_slot') as release:
            jobs.run_job('id', 'path', reservation_token='owner')
        media.assert_not_called()
        release.assert_called_once_with('processing', 'owner')
        self.assertNotIn('path', fail.call_args.args[1])

    def test_failure_update_error_retains_slot_for_recovery(self):
        from backend import jobs
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32}, clear=True), patch.object(jobs.db, 'set_step', side_effect=RuntimeError('secret')), patch.object(jobs.db, 'fail_job', side_effect=RuntimeError('secret')), patch.object(jobs.db, 'release_slot') as release:
            jobs.run_job('id', 'path', reservation_token='owner')
        release.assert_not_called()

    def test_media_validation_is_actionable_and_provider_errors_are_generic(self):
        from backend import jobs
        from backend.utils.audio_processor import MediaValidationError
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32}, clear=True), patch.object(jobs.db, 'set_step'), patch.object(jobs, 'process_input', side_effect=MediaValidationError('Media duration is invalid or exceeds the limit.')), patch.object(jobs.db, 'fail_job') as fail:
            jobs.run_job('id', 'path')
        self.assertIn('duration', fail.call_args.args[1])

    def test_processing_budget_rejects_after_transcription_before_generation_or_indexing(self):
        from backend import jobs
        from backend.core.provider_budget import JobBudgetExceeded
        text = 'A completed transcription'
        segments = [{'text': text, 'start_ms': 0, 'end_ms': 1000, 'timing_precision': 'segment'}]
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32}, clear=True), \
                patch.object(jobs.db, 'set_step'), patch.object(jobs.db, 'fail_job') as fail, \
                patch.object(jobs, 'process_input', return_value=(['audio'], [])), \
                patch.object(jobs, 'transcribe_segments', return_value=segments) as transcribe, \
                patch.object(jobs, 'preflight_processing', side_effect=JobBudgetExceeded('Use a shorter recording.')), \
                patch.object(jobs, 'generate_title') as title, patch.object(jobs, 'summarize') as summary, \
                patch.object(jobs, 'extract_findings') as findings, patch.object(jobs, 'build_rag_chain') as index:
            jobs.run_job('job', 'path')
        transcribe.assert_called_once()
        for remote in (title, summary, findings, index):
            remote.assert_not_called()
        self.assertEqual(fail.call_args.args[1], 'Use a shorter recording.')

    def test_failed_rag_removes_partial_vectors(self):
        from backend import jobs
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32}, clear=True), patch.object(jobs.db, 'set_step'), patch.object(jobs.db, 'fail_job'), patch.object(jobs, 'process_input', return_value=([], [])), patch.object(jobs, 'transcribe_segments', return_value=[{'text': 'transcript', 'start_ms': 0, 'end_ms': 1000, 'timing_precision': 'segment'}]), patch.object(jobs, 'preflight_processing'), patch.object(jobs, 'generate_title', return_value='title'), patch.object(jobs, 'summarize', return_value='summary'), patch.object(jobs, 'extract_findings', return_value={'action_items': '', 'key_decisions': '', 'open_questions': ''}), patch.object(jobs, 'build_rag_chain', side_effect=RuntimeError('indexing failed')), patch.object(jobs, 'delete_vector_store', create=True) as delete:
            jobs.run_job('id', 'path')
        delete.assert_called_once_with('id')


class CLIOwnerTests(unittest.TestCase):
    def test_owner_cli_uses_same_budget_and_rejects_arbitrary_questions(self):
        from contextlib import nullcontext
        from backend import cli

        job = dict(status='done', title='title', summary='', action_items='', key_decisions='', open_questions='')
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32}, clear=True), \
                patch('sys.argv', ['cli', '--owner-evaluation', '--allow-paid', '--tier', 'strong']), \
                patch('builtins.input', side_effect=['arbitrary question', '1', 'exit']), patch('builtins.print'), \
                patch.object(cli, 'get_llm'), patch.object(cli, 'get_embeddings'), patch.object(cli, 'load_ranker'), \
                patch.object(cli, 'profile_for_language') as stt, patch.object(cli, 'run_job') as run, \
                patch.object(cli, 'operation_scope', return_value=nullcontext()) as scope, \
                patch.object(cli.db, 'admit_job', return_value='processing-slot'), patch.object(cli.db, 'get_job', return_value=job), \
                patch.object(cli.db, 'reserve_chat', return_value='chat-slot') as chat, patch.object(cli.db, 'release_slot'), \
                patch.object(cli, 'load_rag_chain', return_value='chain') as load, \
                patch.object(cli, 'ask_question', return_value={'answer': 'twelve'}) as ask:
            cli.main()
        job_id = run.call_args.args[0]
        run.assert_called_once_with(job_id, None, 'english', reservation_token='processing-slot',
                                    owner=True, allow_paid=True, local_owner=True)
        stt.assert_not_called()
        self.assertEqual(chat.call_args.args[0], job_id)
        load.assert_called_once_with(job_id, 'strong')
        ask.assert_called_once_with('chain', cli.OWNER_EVALUATION_QUESTIONS[0])
        self.assertEqual(scope.call_count, 2)
        scope.assert_called_with(job_id, owner=True, allow_paid=True, local_owner=True)
