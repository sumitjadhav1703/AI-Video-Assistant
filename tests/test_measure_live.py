import email
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from scripts import measure_live
from scripts.measure_live import multipart, summary


class MeasureLiveTests(unittest.TestCase):
    def test_multipart_round_trips_fields_and_file(self):
        body, ctype = multipart({'language': 'english', 'demo_acknowledged': 'true'}, 'file', 'clip.mp3', b'\x00\xffdata')
        message = email.message_from_bytes(b'Content-Type: ' + ctype.encode() + b'\r\n\r\n' + body)
        parts = {p.get_param('name', header='content-disposition'): p for p in message.get_payload()}
        self.assertEqual(parts['language'].get_payload(), 'english')
        self.assertEqual(parts['demo_acknowledged'].get_payload(), 'true')
        self.assertEqual(parts['file'].get_filename(), 'clip.mp3')
        self.assertEqual(parts['file'].get_content_type(), 'audio/mpeg')
        self.assertEqual(parts['file'].get_payload(decode=True), b'\x00\xffdata')

    def test_summary_percentiles(self):
        self.assertEqual(summary([3, 1, 2]), {'n': 3, 'min': 1, 'p50': 2, 'p95': 3, 'max': 3})


class FakeBackend:
    def __init__(self, ready_status=200, fail_on=None):
        self.calls, self.ready_status, self.fail_on = [], ready_status, fail_on

    def __call__(self, url, method='GET', body=None, headers=None, timeout=900):
        path = url.split('example.test', 1)[1]
        self.calls.append((method, path))
        if self.fail_on and path.endswith(self.fail_on):
            raise urllib.error.URLError('connection reset')
        if path == '/ready':
            return self.ready_status, 0.1, None
        if path == '/jobs' and method == 'POST':
            return 200, 1.0, {'job_id': 'a' * 32, 'job_token': 'secret-token'}
        if method == 'GET' and path == '/jobs/' + 'a' * 32:
            return 200, 0.1, {'status': 'done', 'step': 'done'}
        return 200, 0.1, {}


class MeasureRunTests(unittest.TestCase):
    def run_with(self, backend):
        with tempfile.NamedTemporaryFile(suffix='.mp3') as media, patch.object(measure_live, 'call', backend), \
                patch.object(measure_live.time, 'sleep'):
            media.write(b'audio')
            media.flush()
            return measure_live.run('https://example.test', media.name, ['Q?'])

    def test_network_failure_still_deletes_and_reports(self):
        backend = FakeBackend(fail_on='/result')
        out = self.run_with(backend)
        self.assertIn('URLError', out['aborted'])
        self.assertIn(('DELETE', '/jobs/' + 'a' * 32), backend.calls)
        self.assertEqual(out['delete']['status'], 200)
        self.assertNotIn('secret-token', repr(out))

    def test_failed_ready_probes_are_counted(self):
        out = self.run_with(FakeBackend(ready_status=503))
        self.assertEqual(out['ready_10']['failed'], 10)
        self.assertEqual(self.run_with(FakeBackend())['ready_10']['failed'], 0)


if __name__ == '__main__':
    unittest.main()
