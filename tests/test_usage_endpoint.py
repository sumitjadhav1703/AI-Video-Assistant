import importlib
import json
import os
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import urlparse

from fastapi.testclient import TestClient

with patch('dotenv.load_dotenv', return_value=False):
    api = importlib.import_module('backend.api')

ROUTE = dict(alias='gemini-flash', tier='economy', provider='gemini', model='gemini/gemini-2.5-flash',
             api_key_env='GEMINI_API_KEY', verified_free=True, input_limit_tokens=20000, rpm=10, tpm=50000, rpd=100)
SECRET = 'AIza-not-a-real-key-but-must-never-leak'


class UsageEndpointTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32, 'DEMO_LIVE_MODE': 'public',
            'JOB_TOKEN_SECRET': 'j' * 32, 'LLM_ROUTES_JSON': json.dumps([ROUTE]), 'GEMINI_API_KEY': SECRET,
            'JOBS_PER_IP_DAY': '1', 'JOBS_GLOBAL_DAY': '5', 'CHATS_PER_IP_DAY': '20', 'CHATS_GLOBAL_DAY': '15',
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(api.app, client=('127.0.0.1', 50000))

    def test_reports_limits_remaining_and_models_without_secrets(self):
        snapshot = {'used': {'jobs_ip_day': 1, 'jobs_global_day': 2, 'chats_ip_minute': 1, 'chats_ip_day': 3,
                             'chats_global_day': 14}, 'resets_at': '2026-11-14T00:00:00+00:00'}
        with patch.object(api.db, 'usage_snapshot', return_value=snapshot) as read:
            response = self.client.get('/usage')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['remaining'], {'analyses_today': 0, 'chats_today': 1, 'chats_this_minute': 1})
        self.assertEqual(body['limits']['analyses_per_visitor_day'], 1)
        self.assertEqual(body['models']['generation']['chat'][0]['model'], 'gemini/gemini-2.5-flash')
        self.assertNotIn(SECRET, response.text)
        self.assertNotIn('api_key', response.text)
        # The caller's identity is the HMAC of the connection address, never a forwarded header.
        self.assertEqual(read.call_args.args[0], api.client_key('127.0.0.1', 's' * 32))

    def test_forwarded_headers_do_not_change_identity(self):
        with patch.object(api.db, 'usage_snapshot', return_value={'used': dict.fromkeys(
                ('jobs_ip_day', 'jobs_global_day', 'chats_ip_minute', 'chats_ip_day', 'chats_global_day'), 0),
                'resets_at': None}) as read:
            self.client.get('/usage', headers={'X-Forwarded-For': '203.0.113.9'})
        self.assertEqual(read.call_args.args[0], api.client_key('127.0.0.1', 's' * 32))

    def test_sample_mode_returns_limits_without_reading_the_database(self):
        with patch.dict(os.environ, {'DEMO_LIVE_MODE': 'sample'}), patch.object(api.db, 'usage_snapshot') as read:
            body = self.client.get('/usage').json()
        read.assert_not_called()
        self.assertEqual(body['mode'], 'sample')
        self.assertIsNone(body['remaining'])

    def test_database_failure_is_a_masked_503(self):
        with patch.object(api.db, 'usage_snapshot', side_effect=RuntimeError('postgresql://user:pw@host')):
            with self.assertLogs('backend.api', level='WARNING'):
                response = self.client.get('/usage')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('postgresql', response.text)


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'isolated loopback Postgres required')
class UsageSnapshotDatabaseTests(unittest.TestCase):
    def test_snapshot_reads_todays_counters_for_one_identity(self):
        import psycopg
        from psycopg.rows import dict_row
        from backend import db
        dsn = os.environ['TEST_DATABASE_URL']
        self.assertIn(urlparse(dsn).hostname, ('localhost', '127.0.0.1', '::1'))
        schema = 'test_usage_' + uuid.uuid4().hex
        with psycopg.connect(dsn) as conn:
            conn.execute(f'CREATE SCHEMA {schema}')
        self.addCleanup(lambda: psycopg.connect(dsn, autocommit=True).execute(f'DROP SCHEMA {schema} CASCADE'))
        with patch.object(db, 'connect', new=lambda: psycopg.connect(dsn, row_factory=dict_row, options=f'-c search_path={schema},public')):
            with db.connect() as conn:
                conn.execute(db.USAGE_SCHEMA)
                day = "date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
                conn.execute(f"INSERT INTO usage_counters VALUES ({day}, 'jobs_ip_day', 'me', 1), ({day}, 'jobs_ip_day', 'other', 1),"
                             f" ({day}, 'chats_ip_day', 'me', 4), ({day}, 'chats_global_day', '*', 9),"
                             f" ({day} - interval '1 day', 'chats_ip_day', 'me', 7)")
            snapshot = db.usage_snapshot('me')
        self.assertEqual(snapshot['used'], {'jobs_ip_day': 1, 'jobs_global_day': 0, 'chats_ip_minute': 0,
                                            'chats_ip_day': 4, 'chats_global_day': 9})


if __name__ == '__main__':
    unittest.main()
