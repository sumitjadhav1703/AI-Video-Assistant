import io
import json
import unittest
from unittest.mock import MagicMock, patch

from scripts import release_render


class RenderReleaseTests(unittest.TestCase):
    sha = 'a' * 40
    service = 'srv-123'
    origin = 'https://sample.onrender.com'
    repo = 'example/ai-video-assistant'
    api = f'https://api.render.com/v1/services/{service}'

    def target(self, **changes):
        return {
            'id': self.service,
            'type': 'web_service',
            'branch': 'main',
            'repo': f'https://github.com/{self.repo}.git',
            'autoDeployTrigger': 'off',
            'serviceDetails': {'url': self.origin, 'runtime': 'docker', 'plan': 'free',
                               'region': 'singapore', 'healthCheckPath': '/health'},
            **changes,
        }

    def deploy(self, request, *, timeout=10):
        with patch.object(release_render, 'request_json', side_effect=request), \
                patch.object(release_render.time, 'sleep'), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            summary = io.StringIO()
            release_render.deploy(self.service, self.origin, self.repo, self.sha, 'key', summary, timeout=timeout)
            return summary.getvalue(), output.getvalue()

    def test_releases_only_exact_sha_then_checks_sample_endpoints(self):
        observed = []
        replies = iter([
            self.target(),
            {'key': 'ENABLE_PROVIDER_CALLS', 'value': 'false'},
            {'key': 'DEMO_LIVE_MODE', 'value': 'sample'},
            {'id': 'dep-123'},
            {'id': 'dep-123', 'status': 'queued'},
            {'id': 'dep-123', 'status': 'live', 'commit': {'id': self.sha}},
            {'status': 'ok'},
            {'status': 'ok'},
            {'mode': 'sample'},
        ])

        def request(url, *, token=None, payload=None, expected_type=dict):
            observed.append((url, token, payload))
            return next(replies)

        summary, output = self.deploy(request)
        self.assertEqual(observed, [
            (self.api, 'key', None),
            (f'{self.api}/env-vars/ENABLE_PROVIDER_CALLS', 'key', None),
            (f'{self.api}/env-vars/DEMO_LIVE_MODE', 'key', None),
            (f'{self.api}/deploys', 'key', {'commitId': self.sha}),
            (f'{self.api}/deploys/dep-123', 'key', None),
            (f'{self.api}/deploys/dep-123', 'key', None),
            (f'{self.origin}/health', None, None),
            (f'{self.origin}/ready', None, None),
            (f'{self.origin}/demo-mode', None, None),
        ])
        self.assertIn('dep-123', summary)
        self.assertIn(self.sha, summary)
        self.assertNotIn('key', summary + output)

    def test_wrong_target_and_inference_config_block_trigger(self):
        for replies in (
            [self.target(autoDeployTrigger='commit')],
            [self.target(branch='staging')],
            [self.target(serviceDetails={'url': 'https://wrong.onrender.com'})],
            [self.target(), {'key': 'ENABLE_PROVIDER_CALLS', 'value': 'true'}],
            [self.target(), {'key': 'ENABLE_PROVIDER_CALLS', 'value': 'false'},
             {'key': 'DEMO_LIVE_MODE', 'value': 'public'}],
        ):
            with self.subTest(replies=replies):
                request = MagicMock(side_effect=replies)
                with self.assertRaises(release_render.DeploymentError):
                    self.deploy(request)
                self.assertFalse(any(call.kwargs.get('payload') for call in request.call_args_list))

    def test_failed_or_mismatched_deploy_stops_before_public_requests(self):
        for status, commit in (('build_failed', self.sha), ('live', 'b' * 40)):
            with self.subTest(status=status):
                request = MagicMock(side_effect=[
                    self.target(), {'key': 'ENABLE_PROVIDER_CALLS', 'value': 'false'},
                    {'key': 'DEMO_LIVE_MODE', 'value': 'sample'}, {'id': 'dep-123'},
                    {'id': 'dep-123', 'status': status, 'commit': {'id': commit}},
                ])
                with self.assertRaises(release_render.DeploymentError):
                    self.deploy(request)
                self.assertEqual(request.call_count, 5)

    def test_queued_without_body_finds_exact_api_deploy_without_reposting(self):
        request = MagicMock(side_effect=[
            self.target(), {'key': 'ENABLE_PROVIDER_CALLS', 'value': 'false'},
            {'key': 'DEMO_LIVE_MODE', 'value': 'sample'}, {},
            [{'deploy': {'id': 'dep-456', 'trigger': 'new_commit', 'commit': {'id': self.sha}}},
             {'deploy': {'id': 'dep-123', 'trigger': 'api', 'commit': {'id': self.sha}}}],
            {'id': 'dep-123', 'status': 'live', 'commit': {'id': self.sha}},
            {'status': 'ok'}, {'status': 'ok'}, {'mode': 'sample'},
        ])
        summary, _ = self.deploy(request)
        self.assertIn('dep-123', summary)
        self.assertEqual(sum(call.kwargs.get('payload') is not None for call in request.call_args_list), 1)
        self.assertIn('createdAfter=', request.call_args_list[4].args[0])
        self.assertEqual(request.call_args_list[5].args[0], f'{self.api}/deploys/dep-123')

    def test_poll_timeout_stops_without_retrying_trigger(self):
        request = MagicMock(side_effect=[
            self.target(), {'key': 'ENABLE_PROVIDER_CALLS', 'value': 'false'},
            {'key': 'DEMO_LIVE_MODE', 'value': 'sample'}, {'id': 'dep-123'},
        ])
        with patch.object(release_render.time, 'monotonic', side_effect=[0, 20]):
            with self.assertRaisesRegex(release_render.DeploymentError, 'timed out'):
                self.deploy(request)
        self.assertEqual(request.call_count, 4)

    def test_redirect_is_rejected_without_logging_response(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 302
        connection.getresponse.return_value.read.return_value = b'private response contents'
        with patch.object(release_render.http.client, 'HTTPSConnection', return_value=connection) as connect:
            with self.assertRaisesRegex(release_render.DeploymentError, '^Render API returned HTTP 302$'):
                release_render.request_json(self.api, token='secret')
        connect.assert_called_once()
        connection.request.assert_called_once()
        connection.close.assert_called_once()

    def test_bounded_json_transport_posts_expected_payload(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 201
        connection.getresponse.return_value.read.return_value = b'{"id":"dep-123"}'
        with patch.object(release_render.http.client, 'HTTPSConnection', return_value=connection):
            response = release_render.request_json(f'{self.api}/deploys', token='key', payload={'commitId': self.sha})
        self.assertEqual(response, {'id': 'dep-123'})
        method, path = connection.request.call_args.args[:2]
        self.assertEqual((method, path), ('POST', f'/v1/services/{self.service}/deploys'))
        self.assertEqual(json.loads(connection.request.call_args.kwargs['body']), {'commitId': self.sha})

    def test_empty_accepted_post_is_reported_as_queued(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 202
        connection.getresponse.return_value.read.return_value = b''
        with patch.object(release_render.http.client, 'HTTPSConnection', return_value=connection):
            self.assertEqual(release_render.request_json(self.api, token='key', payload={'commitId': self.sha}), {})
