"""Operator recovery against an opt-in disposable PostgreSQL schema."""
import io
import json
import os
import re
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import patch

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from backend import db
from backend.usage_limits import JobBusy, JobUnavailable, LimitExceeded, Settings


class InterruptedAPITests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        with patch('dotenv.load_dotenv', return_value=False):
            from backend import api
        self.api = api
        self.client = TestClient(api.app, client=('127.0.0.1', 123))

    def test_interrupted_job_has_actionable_status_and_no_result(self):
        job = {'status': 'interrupted', 'step': 'audio', 'error': 'Please upload again.'}
        with patch.dict(os.environ, {'JOB_TOKEN_SECRET': 'j' * 32}), patch.object(db, 'get_job_status', return_value=job), patch.object(db, 'get_job', return_value=job):
            headers = {'Authorization': 'Bearer ' + self.api._job_token('a' * 32)}
            status = self.client.get('/jobs/' + 'a' * 32, headers=headers)
            result = self.client.get('/jobs/' + 'a' * 32 + '/result', headers=headers)
        self.assertEqual(status.json()['status'], 'interrupted')
        self.assertEqual(result.status_code, 409)
        self.assertIn('upload', result.json()['detail'])

    def test_upload_keeps_slot_if_terminal_job_write_fails(self):
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32, 'DEMO_LIVE_MODE': 'public', 'JOB_TOKEN_SECRET': 'j' * 32}, clear=True), \
                patch.object(self.api, 'preflight_pipeline'), patch.object(self.api, 'profile_for_language'), \
                patch.object(db, 'admit_job', return_value='owner'), patch.object(db, 'release_slot') as release, \
                patch.object(db, 'fail_job', side_effect=RuntimeError('DB unavailable')), patch.object(self.api, 'run_job') as run:
            response = self.client.post('/jobs', data={'demo_acknowledged': 'true'}, files={'file': ('a.wav', b'')})
        self.assertEqual(response.status_code, 400)
        release.assert_not_called()
        run.assert_not_called()

    def test_upload_metrics_use_copied_bytes_and_exclude_content_and_identifiers(self):
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32, 'DEMO_LIVE_MODE': 'public', 'JOB_TOKEN_SECRET': 'j' * 32}, clear=True), \
                patch.object(self.api, 'preflight_pipeline'), patch.object(self.api, 'profile_for_language'), \
                patch.object(db, 'admit_job', return_value='owner'), \
                patch.object(self.api, 'run_job', side_effect=lambda job, path, *args: os.remove(path)), \
                self.assertLogs('uvicorn.error.metrics', level='INFO') as captured:
            response = self.client.post('/jobs', data={'demo_acknowledged': 'true'},
                                        files={'file': ('private.wav', b'private media')})
        self.assertEqual(response.status_code, 200)
        copy, body = captured.output
        self.assertRegex(copy, r'metric=upload_copy bytes=13 elapsed_ms=\d+$')
        received = re.search(r'metric=upload_body bytes=(\d+) complete=True elapsed_ms=\d+$', body)
        self.assertIsNotNone(received)
        self.assertGreater(int(received.group(1)), 13)
        for private in (response.json()['job_id'], 'private.wav', 'private media', 'owner'):
            self.assertNotIn(private, copy + body)


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsn = os.environ['TEST_DATABASE_URL']
        config = conninfo_to_dict(dsn)
        loopback = ('127.0.0.1', 'localhost', '::1')
        if config.get('host') not in loopback or config.get('hostaddr', '127.0.0.1') not in loopback:
            raise ValueError('Tests refuse non-loopback databases')
        schema = 'test_recovery_' + uuid.uuid4().hex
        with psycopg.connect(dsn) as conn:
            conn.execute(f'CREATE SCHEMA {schema}')
        cls.addClassCleanup(cls.drop_schema, dsn, schema)
        cls.database_url = make_conninfo(dsn, options=f'-c search_path={schema},public')

    @staticmethod
    def drop_schema(dsn, schema):
        with psycopg.connect(dsn) as conn:
            conn.execute(f'DROP SCHEMA {schema} CASCADE')

    def setUp(self):
        def connect():
            return psycopg.connect(self.database_url, row_factory=psycopg.rows.dict_row)
        self.enterContext(patch.object(db, 'connect', new=connect))
        with db.connect() as conn:
            conn.execute(db.SCHEMA.replace('CREATE EXTENSION IF NOT EXISTS vector;', ''))
            conn.execute('TRUNCATE transcript_chunks, jobs, usage_counters')
            conn.execute('UPDATE usage_slots SET owner_token=NULL, job_id=NULL')
        with patch.dict(os.environ, {}, clear=True):
            self.settings = Settings.from_env()

    def age_slot(self, slot):
        with db.connect() as conn:
            conn.execute("UPDATE usage_slots SET reserved_at=clock_timestamp()-INTERVAL '1 hour' WHERE name=%s", (slot,))

    def counters(self):
        with db.connect() as conn:
            return conn.execute('SELECT * FROM usage_counters ORDER BY bucket,scope,subject').fetchall()

    def done_job(self):
        db.create_job('done', 'english')
        db.set_step('done', 'rag')
        db.finish_job('done', {key: 'saved' for key in (
            'title', 'transcript', 'summary', 'action_items', 'key_decisions', 'open_questions')})

    def test_recover_processing_preserves_stage_usage_and_other_slot(self):
        self.done_job()
        chat_token = db.reserve_chat('done', 'ip', self.settings)
        token = db.admit_job('crashed', 'english', 'ip', self.settings)
        db.set_step('crashed', 'transcript')
        db.create_job('unrelated', 'english')
        self.age_slot('processing')
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET updated_at=clock_timestamp()-INTERVAL '1 hour' WHERE id='crashed'")
        before = self.counters()
        self.assertNotIn('crashed', db.job_ids_older_than(0))

        db.recover_slot('processing', token, all_workers_stopped=True)

        job = db.get_job_status('crashed')
        self.assertEqual((job['status'], job['step']), ('interrupted', 'transcript'))
        self.assertIn('upload', job['error'].lower())
        self.assertEqual(db.get_job_status('unrelated')['status'], 'queued')
        self.assertEqual(db.job_ids_older_than(0), ['crashed'])
        self.assertEqual([row['owner_token'] for row in db.inspect_slots()], [chat_token])
        self.assertEqual(self.counters(), before)
        self.assertEqual(db.begin_delete('crashed'), 'interrupted')

    def test_recent_processing_progress_blocks_recovery_even_with_old_slot(self):
        token = db.admit_job('working', 'english', 'ip', self.settings)
        self.age_slot('processing')
        db.set_step('working', 'rag')
        self.assertFalse(db.inspect_slots()[0]['stale'])
        with self.assertRaisesRegex(ValueError, 'recent progress'):
            db.recover_slot('processing', token, all_workers_stopped=True)
        with self.assertRaises(LimitExceeded):
            db.admit_job('would-overlap', 'english', 'other-ip', self.settings)
        self.assertEqual(db.get_job_status('working')['status'], 'running')

    def test_chat_recovery_preserves_done_job_and_quotas(self):
        self.done_job()
        job = db.get_job('done')
        token = db.reserve_chat('done', 'ip', self.settings)
        before = self.counters()
        with self.assertRaisesRegex(ValueError, 'stale'):
            db.recover_slot('chat', token, all_workers_stopped=True)
        self.age_slot('chat')
        self.assertTrue(db.inspect_slots()[0]['stale'])
        with self.assertRaises(JobBusy):
            db.begin_delete('done')

        db.recover_slot('chat', token, all_workers_stopped=True)

        self.assertEqual(db.get_job('done'), job)
        self.assertEqual(db.inspect_slots(), [])
        self.assertEqual(self.counters(), before)
        self.assertEqual(db.begin_delete('done'), 'done')

    def test_competing_recovery_cannot_clear_a_replacement_token(self):
        token = db.admit_job('queued-crash', 'english', 'ip', self.settings)
        self.age_slot('processing')
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET updated_at=clock_timestamp()-INTERVAL '1 hour' WHERE id='queued-crash'")

        def attempt():
            try:
                db.recover_slot('processing', token, all_workers_stopped=True)
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(attempt) for _ in range(2)]
            self.assertCountEqual((attempt.result() for attempt in attempts), [True, False])
        self.assertEqual(db.get_job_status('queued-crash')['status'], 'interrupted')
        replacement = db.admit_job('replacement', 'english', 'other-ip', self.settings)
        self.assertFalse(attempt())
        self.assertEqual(db.inspect_slots()[0]['owner_token'], replacement)

    def test_schema_upgrade_ages_existing_slot_conservatively_and_once(self):
        token = db.admit_job('old-schema', 'english', 'ip', self.settings)
        with db.connect() as conn:
            conn.execute('ALTER TABLE usage_slots DROP COLUMN reserved_at')
            conn.execute(db.USAGE_SCHEMA)
        before = db.inspect_slots()[0]
        self.assertEqual(before['owner_token'], token)
        self.assertIsNotNone(before['reserved_at'])
        self.assertFalse(before['stale'])
        with db.connect() as conn:
            conn.execute(db.USAGE_SCHEMA)
        self.assertEqual(db.inspect_slots()[0]['reserved_at'], before['reserved_at'])

    def test_cli_defaults_to_inspection_and_requires_worker_shutdown_acknowledgment(self):
        from backend import recover

        self.done_job()
        token = db.reserve_chat('done', 'ip', self.settings)
        self.age_slot('chat')
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(recover.main([]), 0)
        [slot] = json.loads(output.getvalue())
        self.assertEqual(slot['owner_token'], token)
        self.assertTrue(slot['stale'])
        with self.assertRaises(SystemExit) as rejected, redirect_stderr(io.StringIO()):
            recover.main(['recover', 'chat'])
        self.assertEqual(rejected.exception.code, 2)
        self.assertEqual(db.inspect_slots()[0]['owner_token'], token)
        with patch('getpass.getpass', return_value=token), redirect_stdout(io.StringIO()):
            self.assertEqual(recover.main(['recover', 'chat', '--all-workers-stopped']), 0)
        self.assertEqual(db.inspect_slots(), [])

    def run_worker_with_index(self, *, index_error=False, finish=None):
        from backend import jobs
        from backend.core.vector_store import collection_for

        token = db.admit_job('indexed', 'english', 'ip', self.settings)
        with db.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS langchain_pg_collection (name TEXT PRIMARY KEY)')
            conn.execute('TRUNCATE langchain_pg_collection')

        def build_index(transcript, job_id, documents):
            with db.connect() as conn:
                conn.execute('INSERT INTO langchain_pg_collection VALUES (%s)', (collection_for(job_id),))
            db.save_chunks(job_id, documents)
            if index_error:
                raise RuntimeError('index failed after partial writes')

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32}, clear=True))
            for name, result in (
                ('process_input', ([], [])), ('preflight_processing', None),
                ('transcribe_segments', [{'text': 'Fixture transcript', 'start_ms': 0, 'end_ms': 1000, 'timing_precision': 'segment'}]),
                ('generate_title', 'Fixture title'), ('summarize', 'Saved summary'),
                ('extract_findings', {'action_items': '', 'key_decisions': '', 'open_questions': ''}),
            ):
                stack.enter_context(patch.object(jobs, name, return_value=result))
            stack.enter_context(patch.object(jobs, 'build_rag_chain', side_effect=build_index))
            if finish is not None:
                stack.enter_context(patch.object(db, 'finish_job', side_effect=finish))
            jobs.run_job('indexed', 'fixture.wav', reservation_token=token)
        return token

    def test_worker_preserves_published_index_when_finish_acknowledgment_is_lost(self):
        finish = db.finish_job

        def finish_without_ack(job_id, result):
            finish(job_id, result)
            raise psycopg.OperationalError('simulated lost commit acknowledgment')

        token = self.run_worker_with_index(finish=finish_without_ack)

        job = db.get_job('indexed')
        self.assertEqual((job['status'], job['summary']), ('done', 'Saved summary'))
        self.assertEqual([doc.page_content for doc in db.load_chunks('indexed')], ['Fixture transcript'])
        with db.connect() as conn:
            self.assertEqual(conn.execute('SELECT name FROM langchain_pg_collection').fetchall(), [{'name': 'job_indexed'}])
        self.assertEqual([slot['owner_token'] for slot in db.inspect_slots()], [token])

    def test_worker_removes_partial_index_after_confirming_failure(self):
        self.run_worker_with_index(index_error=True)

        self.assertEqual(db.get_job_status('indexed')['status'], 'error')
        self.assertEqual(db.load_chunks('indexed'), [])
        with db.connect() as conn:
            self.assertEqual(conn.execute('SELECT name FROM langchain_pg_collection').fetchall(), [])
        self.assertEqual(db.inspect_slots(), [])

    def test_finish_job_rejects_a_completed_job(self):
        self.done_job()
        with self.assertRaises(JobUnavailable):
            db.finish_job('done', db.get_job('done'))
