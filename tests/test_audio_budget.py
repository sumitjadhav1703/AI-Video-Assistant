import json
import os
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import patch

from backend.core import audio_budget, transcriber
from backend.usage_limits import LimitExceeded
from stt_fixture import groq_chain

PROFILE = {'provider': 'groq', 'model': 'whisper-large-v3-turbo', 'keyenv': 'GROQ_API_KEY', 'verified_free': True, 'rpm': 2, 'rpd': 3, 'audio_seconds_hour': 30, 'audio_seconds_day': 60}

class AudioBudgetTests(unittest.TestCase):
    def test_groq_redirect_is_not_followed_and_configured_host_is_fixed(self):
        import httpx
        from groq import GroqError

        seen = []

        def respond(transport, request):
            seen.append((request.url.host, request.url.path))
            self.assertIn(b'filename="', request.read())
            return httpx.Response(307, headers={'Location': 'https://unexpected.invalid/collect'})

        profile = SimpleNamespace(model='model', keyenv='GROQ_API_KEY')
        with tempfile.NamedTemporaryFile(suffix='.wav') as sample:
            with wave.open(sample.name, 'wb') as wav:
                wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\x00\x00' * 8000)
            with patch.object(transcriber.audio_budget, 'profile_for_language', return_value=profile), \
                    patch.object(transcriber, 'current_operation', return_value='job'), \
                    patch.object(transcriber.audio_budget, 'reserve_audio_attempt') as reserve, \
                    patch.object(httpx.HTTPTransport, 'handle_request', new=respond), \
                    patch.dict(os.environ, {'GROQ_API_KEY': 'fixture', 'GROQ_BASE_URL': 'https://override.invalid'}):
                with self.assertRaises(GroqError):
                    transcriber._groq_segments(sample.name)
        self.assertEqual(seen, [('api.groq.com', '/openai/v1/audio/transcriptions')])
        reserve.assert_called_once_with('job', profile, 1000)

    def test_sarvam_refuses_redirect_response_without_forwarding_key(self):
        profile = SimpleNamespace(model='model', keyenv='SARVAM_API_KEY')
        with tempfile.NamedTemporaryFile(suffix='.wav') as sample, \
                patch.object(transcriber.audio_budget, 'profile_for_language', return_value=profile), \
                patch.object(transcriber, '_wav_duration_ms', return_value=1000), \
                patch.object(transcriber, 'current_operation', return_value='job'), \
                patch.object(transcriber.audio_budget, 'reserve_audio_attempt') as reserve, \
                patch.object(transcriber.requests, 'post') as post, \
                patch.dict(os.environ, {'SARVAM_API_KEY': 'fixture'}):
            post.return_value.status_code = 307
            with self.assertRaisesRegex(RuntimeError, 'redirect'):
                transcriber._send_to_sarvam(sample.name)
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
            post.return_value.json.assert_not_called()
            reserve.assert_called_once_with('job', profile, 1000)

    def test_profile_must_be_explicit_verified_and_bounded(self):
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32}, clear=True):
            with self.assertRaises((ValueError, RuntimeError)):
                audio_budget.profile_for_language('english')
            for changes in ({'verified_free': False}, {'rpm': 0}, {'model': ''}, {'model': 'https://example.com/model'}, {'model': 'whisper-*'}, {'keyenv': 'OTHER'}):
                bad = dict(PROFILE, **changes)
                with patch.dict(os.environ, {'STT_PROFILES_JSON': json.dumps([bad]), 'GROQ_API_KEY': 'test'}):
                    with self.assertRaises((ValueError, RuntimeError)):
                        audio_budget.profile_for_language('english')
            with patch.dict(os.environ, {'STT_PROFILES_JSON': json.dumps([PROFILE]), 'GROQ_API_KEY': 'test'}):
                self.assertEqual(audio_budget.profile_for_language('english').model, PROFILE['model'])
                with self.assertRaises(ValueError):
                    audio_budget.profile_for_language('unknown')

    def test_quota_denial_prevents_provider_call(self):
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            with wave.open(f.name, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000); wav.writeframes(b'\x00\x00' * 8000)
            with patch('backend.core.transcriber.audio_budget.profile_for_language', return_value=SimpleNamespace(model='model', keyenv='GROQ_API_KEY')), patch('backend.core.transcriber.current_operation', return_value='job'), patch('backend.core.transcriber.audio_budget.reserve_audio_attempt', side_effect=LimitExceeded(60)), patch('backend.core.transcriber.Groq') as client, patch.dict(os.environ, {'GROQ_API_KEY': 'test'}):
                with self.assertRaises(LimitExceeded):
                    transcriber._groq_segments(f.name)
                client.assert_not_called()

    def test_sarvam_piece_quota_denial_does_not_send_extra_audio(self):
        profile = SimpleNamespace(model='model', keyenv='SARVAM_API_KEY')
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            with wave.open(f.name, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000); wav.writeframes(b'\x00\x00' * 210000)
            with patch('backend.core.transcriber.require_provider_calls'), patch('backend.core.transcriber.audio_budget.profile_for_language', return_value=profile), patch('backend.core.transcriber.current_operation', return_value='job'), patch('backend.core.transcriber.audio_budget.reserve_audio_attempt', side_effect=[1, LimitExceeded(60)]) as reserve, patch('backend.core.transcriber.requests.post') as post, patch.dict(os.environ, {'SARVAM_API_KEY': 'test'}):
                post.return_value.ok = True
                post.return_value.json.return_value = {'transcript': 'first'}
                with self.assertRaises(LimitExceeded):
                    transcriber.transcribe_segments([f.name], 'hinglish')
                self.assertEqual(post.call_count, 1)
                self.assertEqual([call.args[2] for call in reserve.call_args_list], [25000, 1250])

    def test_cli_preflight_rejects_unapproved_profile_before_admission(self):
        from backend import cli
        with patch.object(cli, 'require_provider_calls'), patch.object(cli, 'get_llm'), patch.object(cli, 'get_embeddings'), patch.object(cli, 'load_ranker'), patch.object(cli, 'profile_for_language', side_effect=ValueError('unapproved'), create=True) as profile, patch.object(cli.db, 'admit_job') as admit, patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 'x' * 32}):
            with self.assertRaises(ValueError):
                cli.run_pipeline('audio.wav')
            profile.assert_called_once_with('english')
            admit.assert_not_called()

    def test_failed_provider_call_keeps_prior_reservation(self):
        profile = SimpleNamespace(model='model', keyenv='GROQ_API_KEY')
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            with wave.open(f.name, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000); wav.writeframes(b'\x00\x00' * 8000)
            with patch('backend.core.transcriber.audio_budget.profile_for_language', return_value=profile), patch('backend.core.transcriber.current_operation', return_value='job'), patch('backend.core.transcriber.audio_budget.reserve_audio_attempt', return_value=1) as reserve, patch('backend.core.transcriber.Groq') as client, patch.dict(os.environ, {'GROQ_API_KEY': 'test'}):
                client.return_value.audio.transcriptions.create.side_effect = RuntimeError('provider failed')
                with self.assertRaises(RuntimeError):
                    transcriber._groq_segments(f.name)
                reserve.assert_called_once_with('job', profile, 1000)
                client.return_value.audio.transcriptions.create.assert_called_once()


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'isolated loopback Postgres required')
class AudioBudgetDatabaseTests(unittest.TestCase):
    def test_reservations_survive_connections_and_job_deletion(self):
        import uuid
        from urllib.parse import urlparse
        import psycopg
        from psycopg.rows import dict_row
        from backend import db
        dsn = os.environ['TEST_DATABASE_URL']
        if urlparse(dsn).hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Tests refuse non-loopback databases')
        schema = 'test_audio_' + uuid.uuid4().hex
        with psycopg.connect(dsn) as conn:
            conn.execute(f'CREATE SCHEMA {schema}')
        try:
            connect = lambda: psycopg.connect(dsn, row_factory=dict_row, options=f'-c search_path={schema},public')
            with patch.object(db, 'connect', new=connect):
                with connect() as conn:
                    conn.execute('CREATE TABLE usage_guard (id integer PRIMARY KEY)')
                    conn.execute('INSERT INTO usage_guard VALUES (1)')
                    conn.execute(audio_budget.AUDIO_SCHEMA)
                    conn.execute('CREATE TABLE jobs (id text PRIMARY KEY)')
                    conn.execute("INSERT INTO jobs VALUES ('deleted-job')")
                profile = audio_budget.AudioProfile(**dict(PROFILE, rpm=1))
                audio_budget.reserve_audio_attempt('deleted-job', profile, 1000)
                with connect() as conn:
                    conn.execute("DELETE FROM jobs WHERE id='deleted-job'")
                with self.assertRaises(LimitExceeded):
                    audio_budget.reserve_audio_attempt('new-job', profile, 1000)
                with connect() as conn:
                    self.assertEqual(conn.execute('SELECT count(*) AS n FROM audio_attempts').fetchone()['n'], 1)
        finally:
            with psycopg.connect(dsn) as conn:
                conn.execute(f'DROP SCHEMA {schema} CASCADE')

class TimestampBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(groq_chain())

    def test_submillisecond_out_of_bounds_and_reverse_times_are_rejected(self):
        # A 0.1 ms end overshoot is clamped to the chunk (see test_timestamps); larger errors still fail.
        cases = [(-0.0001, 0.1), (0, 2.0001), (0.3004, 0.3003)]
        for start, end in cases:
            with self.subTest(start=start, end=end), patch('backend.core.transcriber._wav_duration_ms', return_value=1000), patch('backend.core.transcriber._groq_segments', return_value=[{'text': 'hello', 'start': start, 'end': end}]):
                with self.assertRaises(ValueError):
                    transcriber.transcribe_segments(['fake.wav'])
