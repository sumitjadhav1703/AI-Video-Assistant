"""Transcription fallback chain: ordering, eligibility, and moving on when a route fails."""
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from backend.core import audio_budget, transcriber
from backend.core.audio_budget import AudioProfile
from backend.core.llm_gateway import operation_scope

LIMITS = dict(rpm=10, rpd=100, audio_seconds_hour=3600, audio_seconds_day=7200)
GROQ = dict(provider='groq', model='whisper-large-v3-turbo', keyenv='GROQ_API_KEY', verified_free=True, **LIMITS)
GROQ_V3 = {**GROQ, 'model': 'whisper-large-v3'}
GEMINI = dict(provider='gemini', model='gemini-3.5-flash-lite', keyenv='GEMINI_API_KEY', verified_free=True, **LIMITS)
META = dict(provider='meta', model='muse-voice-transcribe-1.0', keyenv='META_API_KEY', verified_free=False, **LIMITS)
KEYS = {name: 'offline' for name in ('GROQ_API_KEY', 'GEMINI_API_KEY', 'META_API_KEY')}


def env(*profiles, **extra):
    return {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 'x' * 32,
            'STT_PROFILES_JSON': json.dumps(list(profiles)), **KEYS, **extra}


class ChainConfigTests(unittest.TestCase):
    def chain(self, *profiles, **extra):
        with patch.dict(os.environ, env(*profiles, **extra), clear=True):
            return [(p.provider, p.model) for p in audio_budget.profiles_for_language('english')]

    def test_configured_order_is_kept_and_meta_is_always_last(self):
        both = dict(ENABLE_PAID_META='true', ENABLE_PUBLIC_PAID_FALLBACK='true')
        self.assertEqual(self.chain(META, GROQ, GROQ_V3, GEMINI, **both),
                         [('groq', 'whisper-large-v3-turbo'), ('groq', 'whisper-large-v3'),
                          ('gemini', 'gemini-3.5-flash-lite'), ('meta', 'muse-voice-transcribe-1.0')])

    def test_paid_meta_needs_both_flags_and_missing_keys_are_skipped(self):
        self.assertNotIn('meta', [p for p, _ in self.chain(GROQ, META, ENABLE_PAID_META='true')])
        self.assertNotIn('meta', [p for p, _ in self.chain(GROQ, META, ENABLE_PUBLIC_PAID_FALLBACK='true')])
        with patch.dict(os.environ, {**env(GROQ, GEMINI), 'GEMINI_API_KEY': ''}, clear=True):
            self.assertEqual([p.provider for p in audio_budget.profiles_for_language('english')], ['groq'])

    def test_invalid_profiles_are_rejected(self):
        mistral = {**GROQ, 'provider': 'mistral', 'keyenv': 'MISTRAL_API_KEY'}  # paid only, unsupported
        for bad in ([GROQ, GROQ], [{**META, 'verified_free': True}], [{**GEMINI, 'verified_free': False}], [mistral],
                    [{**GEMINI, 'keyenv': 'GROQ_API_KEY'}], [{**GROQ, 'provider': 'openai'}]):
            with self.subTest(bad=bad), patch.dict(os.environ, env(*bad), clear=True):
                with self.assertRaisesRegex(ValueError, 'transcription profile'):
                    audio_budget.profiles_for_language('english')


class ChunkFallbackTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = str(Path(directory) / 'chunk.wav')
        with wave.open(self.path, 'wb') as handle:
            handle.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            handle.writeframes(b'\x00\x00' * 8000 * 120)  # 120 s
        self.enterContext(patch.dict(os.environ, env(GROQ, GROQ_V3, GEMINI), clear=True))
        self.enterContext(operation_scope('job-1'))
        self.metrics = self.enterContext(patch.object(transcriber, 'metric'))

    def speech(self, seconds, words_per_segment=40, overshoot=0):
        return [{'text': ' '.join(['word'] * words_per_segment), 'start': start, 'end': min(start + 10, seconds) + overshoot}
                for start in range(0, seconds, 10)]

    def test_failed_route_falls_back_to_the_next(self):
        with patch.object(transcriber, '_groq_segments', side_effect=[RuntimeError('503'), self.speech(120)]) as groq:
            segments = transcriber.transcribe_segments([self.path])
        self.assertEqual([call.args[1].model for call in groq.call_args_list], ['whisper-large-v3-turbo', 'whisper-large-v3'])
        self.assertEqual(segments[-1]['end_ms'], 120000)
        self.assertEqual(segments[0]['timing_precision'], 'segment')
        self.metrics.assert_any_call('stt_fallback', provider='groq', model='whisper-large-v3', position=1)

    def test_invalid_output_and_quota_errors_also_fall_back(self):
        for failure in (audio_budget.LimitExceeded(60), [{'text': 'x', 'start': 0, 'end': 400}], []):
            with self.subTest(failure=failure), patch.object(transcriber, '_groq_segments', side_effect=[failure, self.speech(120)]
                                                             if isinstance(failure, Exception) else [failure, self.speech(120)]):
                self.assertEqual(len(transcriber.transcribe_segments([self.path])), 12)

    def test_truncated_chat_transcript_and_approximate_timestamps(self):
        failing = {'side_effect': RuntimeError('down')}
        with patch.object(transcriber, '_groq_segments', **failing), \
                patch.object(transcriber, '_gemini_segments', return_value=self.speech(120, overshoot=2)):
            segments = transcriber.transcribe_segments([self.path])
        self.assertEqual((segments[-1]['end_ms'], segments[0]['timing_precision']), (120000, 'piece'))
        with patch.object(transcriber, '_groq_segments', **failing), \
                patch.object(transcriber, '_gemini_segments', return_value=[{'text': 'only five words here now', 'start': 0, 'end': 120}]):
            with self.assertRaisesRegex(ValueError, 'truncated'):
                transcriber.transcribe_segments([self.path])

    def test_auth_failures_are_skipped_for_later_chunks(self):
        denied = RuntimeError('401')
        denied.status_code = 401
        with patch.object(transcriber, '_groq_segments', side_effect=[denied, self.speech(120), self.speech(120)]) as groq:
            transcriber.transcribe_segments([self.path, self.path])
        self.assertEqual([call.args[1].model for call in groq.call_args_list],
                         ['whisper-large-v3-turbo', 'whisper-large-v3', 'whisper-large-v3'])

    def test_all_routes_failing_raises_the_last_error(self):
        with patch.object(transcriber, '_groq_segments', side_effect=[RuntimeError('a'), RuntimeError('b')]), \
                patch.object(transcriber, '_gemini_segments', side_effect=RuntimeError('c')):
            with self.assertRaisesRegex(RuntimeError, 'c'):
                transcriber.transcribe_segments([self.path])

    def test_meta_asr_sends_parallel_wav_pieces_with_millisecond_turns(self):
        profile = AudioProfile(**META)
        calls = []

        def reply(url, **kwargs):
            calls.append((url, kwargs))
            return {'turns': [{'turnId': 0, 'startMs': 500, 'endMs': 4000, 'transcript': 'hello'}, {'transcript': ''}]}
        with patch.object(transcriber.audio_budget, 'reserve_audio_attempt') as reserve, \
                patch.object(transcriber, '_post_json', side_effect=reply):
            segments = transcriber._meta_segments(self.path, profile)
        self.assertEqual(len(calls), 4)  # 120 s in 30 s pieces
        url, kwargs = calls[0]
        self.assertEqual(url, 'https://api.meta.ai/v1/asr/transcribe')
        self.assertEqual(json.loads(kwargs['files']['request'][1]),
                         {'model': 'muse-voice-transcribe-1.0', 'mode': 'ENDPOINTING', 'audioEncoding': 'WAV', 'languageBias': ['en']})
        self.assertTrue(kwargs['files']['audio'][1].startswith(b'RIFF'))
        self.assertEqual(sorted((s['start'], s['end']) for s in segments), [(0.5, 4.0), (30.5, 34.0), (60.5, 64.0), (90.5, 94.0)])
        reserve.assert_called_once()
        self.assertEqual(reserve.call_args.args[2], 120000)

if __name__ == '__main__':
    unittest.main()
