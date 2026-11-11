"""Opt-in transaction tests using a disposable schema on loopback PostgreSQL."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from threading import Barrier
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from backend import db
from backend.usage_limits import Settings, LimitExceeded, JobBusy, JobUnavailable


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'set TEST_DATABASE_URL to an isolated local PostgreSQL')
class DatabaseLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['TEST_DATABASE_URL']
        if urlparse(cls.dsn).hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Tests refuse non-loopback databases')
        cls.schema = 'test_limits_' + uuid.uuid4().hex
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(f'CREATE SCHEMA {cls.schema}')
        cls.connection_patch = patch.object(db, 'connect', new=lambda: psycopg.connect(cls.dsn, row_factory=dict_row, options=f'-c search_path={cls.schema},public'))
        cls.connection_patch.start()
        with db.connect() as conn:
            conn.execute(db.SCHEMA.replace('CREATE EXTENSION IF NOT EXISTS vector;', ''))

    @classmethod
    def tearDownClass(cls):
        cls.connection_patch.stop()
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    def setUp(self):
        with db.connect() as conn:
            conn.execute('TRUNCATE transcript_chunks, jobs, usage_counters')
            conn.execute('UPDATE usage_slots SET owner_token=NULL, job_id=NULL')
        with patch.dict(os.environ, {}, clear=True):
            self.settings = Settings.from_env()

    def admit(self, identity='ip', settings=None):
        job_id = uuid.uuid4().hex
        token = db.admit_job(job_id, 'english', identity, settings or self.settings)
        return job_id, token

    def test_parallel_admission_has_one_winner(self):
        def attempt(_):
            try:
                return self.admit()
            except LimitExceeded:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(result is not None for result in results), 1)
        with db.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS count FROM jobs').fetchone()['count'], 1)
            counts = conn.execute('SELECT count FROM usage_counters').fetchall()
        self.assertTrue(all(row['count'] == 1 for row in counts))

    def test_daily_limits_survive_job_deletion(self):
        for _ in range(self.settings.jobs_per_ip_day):
            job_id, token = self.admit()
            db.release_slot('processing', token)
            db.fail_job(job_id, 'synthetic failure')
            db.delete_job(job_id)
        with self.assertRaises(LimitExceeded):
            self.admit()

    def test_cleanup_uses_terminal_update_time(self):
        for job_id in ('old', 'recent', 'active', 'unknown', 'legacy-deleting'):
            db.create_job(job_id, 'english')
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET status='done', updated_at=NOW()-INTERVAL '25 hours' WHERE id='old'")
            conn.execute("UPDATE jobs SET status='done', created_at=NOW()-INTERVAL '2 days' WHERE id='recent'")
            conn.execute("UPDATE jobs SET status='running', updated_at=NOW()-INTERVAL '2 days' WHERE id='active'")
            conn.execute("UPDATE jobs SET status='unknown', updated_at=NOW()-INTERVAL '2 days' WHERE id='unknown'")
            conn.execute("UPDATE jobs SET status='deleting', updated_at=NOW()-INTERVAL '2 days' WHERE id='legacy-deleting'")
        self.assertCountEqual(db.job_ids_older_than(1), ['old', 'legacy-deleting'])
        db.delete_job('legacy-deleting')
        self.assertIsNone(db.get_job_status('legacy-deleting'))

    def test_global_limit_applies_across_ips(self):
        settings = replace(self.settings, jobs_global_day=2)
        for identity in ('a', 'b'):
            _, token = self.admit(identity, settings)
            db.release_slot('processing', token)
        with self.assertRaises(LimitExceeded):
            self.admit('c', settings)

    def test_failed_job_insert_rolls_back_quota_and_slot(self):
        db.create_job('duplicate', 'english')
        with self.assertRaises(psycopg.errors.UniqueViolation):
            db.admit_job('duplicate', 'english', 'ip', self.settings)
        _, token = self.admit()
        db.release_slot('processing', token)
        with db.connect() as conn:
            counts = conn.execute('SELECT count FROM usage_counters').fetchall()
        self.assertTrue(all(row['count'] == 1 for row in counts))

    def test_wrong_owner_cannot_release_slot(self):
        _, token = self.admit()
        db.release_slot('processing', 'wrong-owner')
        with self.assertRaises(LimitExceeded):
            self.admit('another-ip')
        db.release_slot('processing', token)
        self.admit('another-ip')

    def test_chat_limits_and_active_chat_delete_are_atomic(self):
        job_id, token = self.admit()
        db.release_slot('processing', token)
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET status='done' WHERE id=%s", (job_id,))
        settings = replace(self.settings, chats_per_job_day=2)
        for i in range(2):
            chat_token = db.reserve_chat(job_id, f'ip{i}', settings)
            with self.assertRaises(JobBusy):
                db.delete_job(job_id)
            db.release_slot('chat', chat_token)
        with self.assertRaises(LimitExceeded):
            db.reserve_chat(job_id, 'other-ip', settings)

    def test_chat_and_delete_cannot_both_win(self):
        job_id = uuid.uuid4().hex
        db.create_job(job_id, 'english')
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET status='done' WHERE id=%s", (job_id,))
        start = Barrier(2, timeout=5)

        def chat():
            start.wait()
            try:
                return db.reserve_chat(job_id, 'ip', self.settings)
            except JobUnavailable:
                return None

        def delete():
            start.wait()
            try:
                db.delete_job(job_id)
                return True
            except JobBusy:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            chat_result = pool.submit(chat)
            delete_result = pool.submit(delete)
            chat_token = chat_result.result(timeout=10)
            deleted = delete_result.result(timeout=10)
        self.assertNotEqual(bool(chat_token), deleted)
        self.assertEqual(db.get_job_status(job_id) is None, deleted)
        if chat_token:
            db.release_slot('chat', chat_token)

    def test_active_job_cannot_be_deleted_or_cleanup_selected(self):
        job_id, _ = self.admit()
        with self.assertRaises(JobBusy):
            db.delete_job(job_id)
        self.assertEqual(db.job_ids_older_than(0), [])

    def test_old_buckets_pruned_without_resetting_current_usage(self):
        with db.connect() as conn:
            conn.execute("INSERT INTO usage_counters VALUES (NOW()-INTERVAL '3 days','old','identity',3)")
        self.admit()
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS count FROM usage_counters WHERE scope='old'").fetchone()['count'], 0)
            self.assertEqual(conn.execute("SELECT count FROM usage_counters WHERE scope='jobs_ip_day'").fetchone()['count'], 1)

    def test_chat_ip_minute_day_and_global_limits(self):
        for field in ('chats_per_ip_minute', 'chats_per_ip_day', 'chats_global_day'):
            with self.subTest(field=field):
                self.setUp()
                job_id, token = self.admit()
                db.release_slot('processing', token)
                with db.connect() as conn:
                    conn.execute("UPDATE jobs SET status='done' WHERE id=%s", (job_id,))
                settings = replace(self.settings, **{field: 2})
                for _ in range(2):
                    token = db.reserve_chat(job_id, 'ip', settings)
                    db.release_slot('chat', token)
                with self.assertRaises(LimitExceeded):
                    db.reserve_chat(job_id, 'other-ip' if field == 'chats_global_day' else 'ip', settings)

    def test_utc_buckets_come_from_database_clock(self):
        _, token = self.admit()
        db.release_slot('processing', token)
        with db.connect() as conn:
            buckets = conn.execute("SELECT bucket AT TIME ZONE 'UTC' AS bucket FROM usage_counters").fetchall()
        self.assertTrue(all(row['bucket'].hour == 0 and row['bucket'].minute == 0 for row in buckets))


    def test_failed_api_delete_rolls_back_artifacts_and_can_be_retried(self):
        from fastapi.testclient import TestClient
        from backend import api

        target = 'a' * 32
        other = 'b' * 32
        slot = db.admit_job(target, 'english', 'ip', self.settings)
        db.release_slot('processing', slot)
        db.create_job(other, 'english')
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET status='done'")
            conn.execute('CREATE TABLE langchain_pg_collection (uuid text PRIMARY KEY, name text UNIQUE)')
            conn.execute('''CREATE TABLE langchain_pg_embedding (
                id text PRIMARY KEY, collection_id text REFERENCES langchain_pg_collection(uuid) ON DELETE CASCADE)''')
            for job_id in (target, other):
                conn.execute('INSERT INTO langchain_pg_collection VALUES (%s,%s)', (job_id, f'job_{job_id}'))
                conn.execute('INSERT INTO langchain_pg_embedding VALUES (%s,%s)', (job_id, job_id))
                conn.execute("INSERT INTO transcript_chunks VALUES (%s,%s,0,'synthetic',NULL,NULL,'unknown')",
                             (job_id, job_id))
            conn.execute('CREATE TABLE audit_delete_guard (job_id text REFERENCES jobs(id))')
            conn.execute('INSERT INTO audit_delete_guard VALUES (%s)', (target,))
            counters = conn.execute('SELECT * FROM usage_counters ORDER BY scope').fetchall()

        def artifacts():
            with db.connect() as conn:
                return [conn.execute(query).fetchall() for query in (
                    'SELECT id FROM jobs ORDER BY id',
                    'SELECT job_id AS id FROM transcript_chunks ORDER BY job_id',
                    'SELECT id FROM langchain_pg_embedding ORDER BY id',
                )]

        with patch.dict(os.environ, {'JOB_TOKEN_SECRET': 'j' * 32}):
            client = TestClient(api.app)
            headers = {'Authorization': 'Bearer ' + api._job_token(target)}
            self.assertEqual(client.delete(f'/jobs/{target}', headers=headers).status_code, 503)
            self.assertEqual(db.get_job_status(target)['status'], 'done')
            self.assertEqual(artifacts(), [[{'id': target}, {'id': other}]] * 3)
            with db.connect() as conn:
                conn.execute('DROP TABLE audit_delete_guard')
            self.assertEqual(client.delete(f'/jobs/{target}', headers=headers).status_code, 200)

        self.assertEqual(artifacts(), [[{'id': other}]] * 3)
        with db.connect() as conn:
            self.assertEqual(conn.execute('SELECT * FROM usage_counters ORDER BY scope').fetchall(), counters)
            conn.execute('DROP TABLE langchain_pg_embedding, langchain_pg_collection')

    def test_positive_api_upload_result_chat_delete_preserves_usage(self):
        from fastapi.testclient import TestClient
        with patch('dotenv.load_dotenv', return_value=False):
            from backend import api, jobs
        expected = {
            'title': 'Project meeting', 'transcript': 'Alice will ship the demo Friday.',
            'summary': 'A demo was planned.', 'action_items': 'Alice: ship demo Friday.',
            'key_decisions': 'Ship the demo.', 'open_questions': 'None.',
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32,
                'DEMO_LIVE_MODE': 'public', 'JOB_TOKEN_SECRET': 'j' * 32,
            }, clear=True))
            for name, result in (
                ('process_input', ([], [])), ('transcribe_segments', [{'text': expected['transcript'], 'start_ms': 0, 'end_ms': 1000, 'timing_precision': 'segment'}]),
                ('generate_title', expected['title']), ('summarize', expected['summary']),
                ('extract_findings', {key: expected[key] for key in ('action_items', 'key_decisions', 'open_questions')}),
                ('build_rag_chain', None),
            ):
                stack.enter_context(patch.object(jobs, name, return_value=result))
            stack.enter_context(patch.object(api, 'preflight_pipeline'))
            stack.enter_context(patch.object(api, 'profile_for_language'))
            stack.enter_context(patch.object(jobs, 'preflight_processing'))
            stack.enter_context(patch.object(api, 'load_rag_chain', return_value=object()))
            stack.enter_context(patch.object(api, 'ask_question', return_value={'answer': 'Alice will ship it Friday.', 'abstained': False, 'citations': []}))
            client = TestClient(api.app, client=('203.0.113.1', 123))
            started = client.post('/jobs', files={'file': ('meeting.wav', b'mocked media')}, data={'language': 'english', 'demo_acknowledged': 'true'})
            self.assertEqual(started.status_code, 200, started.text)
            job_id = started.json()['job_id']
            client.headers['Authorization'] = 'Bearer ' + started.json()['job_token']
            status = client.get(f'/jobs/{job_id}')
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()['status'], 'done')
            self.assertEqual(status.json()['step'], 'done')
            result = client.get(f'/jobs/{job_id}/result')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json(), {'job_id': job_id, **expected})
            answer = client.post(f'/jobs/{job_id}/chat', json={'question': 'Who will ship the demo?'})
            self.assertEqual(answer.status_code, 200, answer.text)
            self.assertEqual(answer.json()['answer'], 'Alice will ship it Friday.')
            with db.connect() as conn:
                usage_before = conn.execute('SELECT bucket,scope,subject,count FROM usage_counters ORDER BY scope,subject').fetchall()
                self.assertEqual(len(usage_before), 6)
                self.assertTrue(all(row['count'] == 1 for row in usage_before))
                self.assertTrue(all(row['owner_token'] is None for row in conn.execute('SELECT owner_token FROM usage_slots')))
            deleted = client.delete(f'/jobs/{job_id}')
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertTrue(deleted.json()['deleted'])
            self.assertEqual(client.get(f'/jobs/{job_id}').status_code, 404)
            with db.connect() as conn:
                self.assertEqual(conn.execute('SELECT count(*) AS count FROM jobs').fetchone()['count'], 0)
                usage_after = conn.execute('SELECT bucket,scope,subject,count FROM usage_counters ORDER BY scope,subject').fetchall()
            self.assertEqual(usage_after, usage_before)
