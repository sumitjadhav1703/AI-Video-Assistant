"""Regression tests for defects found in the 2026-11 engineering audit (see docs/engineering-audit/bugs-and-fixes.md)."""
import os
import unittest
from unittest.mock import patch

from backend.core import chunks, guardrails, transcriber
from backend.usage_limits import Settings


class GuardrailRegressionTests(unittest.TestCase):
    def test_card_inside_a_longer_digit_run_is_still_redacted(self):
        # A greedy 13-19 digit match swallowed the neighbouring group, failed Luhn, and left the card visible.
        for text in ('ref 04370 4111 1111 1111 1111 seats', 'seats 4111 1111 1111 1111 40-66'):
            with self.subTest(text=text):
                self.assertNotIn('4111 1111 1111 1111', guardrails.sanitize_text(text))

    def test_tab_separated_card_is_redacted(self):
        self.assertNotIn('4111', guardrails.sanitize_text('card 4111\t1111\t1111\t1111 end'))

    def test_redaction_keeps_text_length(self):
        text = 'mail a.b@example.com or call +91 98765 43210'
        self.assertEqual(len(guardrails.sanitize_text(text)), len(text))


class ChunkRegressionTests(unittest.TestCase):
    @staticmethod
    def _segments(length):
        return [{'text': 'x' * length, 'start_ms': 0, 'end_ms': 1000, 'timing_precision': 'segment'}]

    def test_short_tail_is_folded_into_the_previous_chunk(self):
        docs = chunks.prepare_documents(self._segments(951), 'job')
        self.assertEqual([len(doc.page_content) for doc in docs], [500, 501])

    def test_long_tail_still_gets_its_own_chunk(self):
        docs = chunks.prepare_documents(self._segments(1100), 'job')
        self.assertEqual([len(doc.page_content) for doc in docs], [500, 500, 200])

    def test_chunks_cover_the_whole_text(self):
        for length in (1, 499, 500, 550, 551, 950, 1000, 4321):
            docs = chunks.prepare_documents(self._segments(length), 'job')
            self.assertEqual(docs[-1].page_content, ('x' * length)[-len(docs[-1].page_content):])
            self.assertTrue(all(len(doc.page_content) <= 550 for doc in docs))


class TimestampRegressionTests(unittest.TestCase):
    def test_segment_starting_inside_slack_past_the_chunk_is_clamped(self):
        segments = transcriber._normalize_segments(
            [{'text': 'a', 'start': 0, 'end': 9.5}, {'text': 'b', 'start': 10.4, 'end': 10.6}],
            10000, 'segment', 1000)
        self.assertEqual([(s['start_ms'], s['end_ms']) for s in segments], [(0, 9500), (10000, 10000)])


class LimitRegressionTests(unittest.TestCase):
    def test_chats_per_ip_day_is_capped_like_the_other_limits(self):
        with patch.dict(os.environ, {'CHATS_PER_IP_DAY': '100000'}):
            self.assertEqual(Settings.from_env().chats_per_ip_day, 20)


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'isolated loopback Postgres required')
class AttemptHistoryPruneTests(unittest.TestCase):
    def test_only_attempts_older_than_every_quota_window_are_pruned(self):
        import uuid
        from urllib.parse import urlparse
        import psycopg
        from psycopg.rows import dict_row
        from backend import db
        from backend.core.audio_budget import AUDIO_SCHEMA
        from backend.core.provider_budget import BUDGET_SCHEMA
        dsn = os.environ['TEST_DATABASE_URL']
        self.assertIn(urlparse(dsn).hostname, ('localhost', '127.0.0.1', '::1'))
        schema = 'test_prune_' + uuid.uuid4().hex
        with psycopg.connect(dsn) as conn:
            conn.execute(f'CREATE SCHEMA {schema}')
        self.addCleanup(lambda: psycopg.connect(dsn, autocommit=True).execute(f'DROP SCHEMA {schema} CASCADE'))
        connect = lambda: psycopg.connect(dsn, row_factory=dict_row, options=f'-c search_path={schema},public')
        with patch.object(db, 'connect', new=connect):
            with db.connect() as conn:
                conn.execute(BUDGET_SCHEMA + AUDIO_SCHEMA)
                for age in ('2 days', '8 days'):
                    conn.execute("INSERT INTO provider_attempts(job_id,route_alias,provider,input_tokens,output_tokens,created_at) "
                                 "VALUES ('j','a','groq',1,1,clock_timestamp() - %s::interval)", (age,))
                    conn.execute("INSERT INTO audio_attempts(job_id,provider,model,duration_ms,created_at) "
                                 "VALUES ('j','groq','m',1,clock_timestamp() - %s::interval)", (age,))
            db.prune_attempt_history()
            with db.connect() as conn:
                for table in ('provider_attempts', 'audio_attempts'):
                    self.assertEqual(conn.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n'], 1)


if __name__ == '__main__':
    unittest.main()
