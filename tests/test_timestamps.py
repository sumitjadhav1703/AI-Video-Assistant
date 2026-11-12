import unittest
from unittest.mock import patch
from backend.core.transcriber import transcribe_segments
from stt_fixture import groq_chain

class TimestampsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(groq_chain())

    def test_small_whisper_overshoot_is_clamped_and_large_errors_fail(self):
        segments = [{'text': 'one', 'start': 0, 'end': 0.5}, {'text': 'two', 'start': 0.49, 'end': 1.006}]
        with patch('backend.core.transcriber._wav_duration_ms', return_value=1000), \
                patch('backend.core.transcriber._groq_segments', return_value=segments):
            result = transcribe_segments(['a'])
        self.assertEqual([(s['start_ms'], s['end_ms']) for s in result], [(0, 500), (500, 1000)])
        for bad in ([{'text': 'x', 'start': 0, 'end': 4.5}], [{'text': 'x', 'start': 0, 'end': 3},
                                                             {'text': 'y', 'start': 1, 'end': 2}],
                    [{'text': 'x', 'start': 0.8, 'end': 0.2}]):
            with self.subTest(bad=bad), patch('backend.core.transcriber._wav_duration_ms', return_value=3000), \
                    patch('backend.core.transcriber._groq_segments', return_value=bad), self.assertRaises(ValueError):
                transcribe_segments(['a'])

    def test_offsets_use_real_wav_duration_and_bad_timestamps_fail(self):
        with patch('backend.core.transcriber._wav_duration_ms', side_effect=[1200, 2300]), patch('backend.core.transcriber._groq_segments', side_effect=[[{'text':'one', 'start':0, 'end':1}], [{'text':'two', 'start':0.1, 'end':1.5}]]):
            result = transcribe_segments(['a', 'b'])
        self.assertEqual((result[1]['start_ms'], result[1]['end_ms']), (1300, 2700))
        with patch('backend.core.transcriber._wav_duration_ms', return_value=1000), patch('backend.core.transcriber._groq_segments', return_value=[{'text':'bad', 'start':0, 'end':float('nan')}]):
            with self.assertRaises(ValueError):
                transcribe_segments(['a'])

    def test_real_wav_duration_and_empty_transcript(self):
        import tempfile
        import wave
        from backend.core.transcriber import _wav_duration_ms
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            with wave.open(f.name, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(8000)
                wav.writeframes(b'\x00\x00' * 12000)
            self.assertEqual(_wav_duration_ms(f.name), 1500)
            with patch('backend.core.transcriber._groq_segments', return_value=[]):
                with self.assertRaises(ValueError):
                    transcribe_segments([f.name])

    def test_sarvam_piece_has_coarse_bounds(self):
        import tempfile
        import wave
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            with wave.open(f.name, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(8000)
                wav.writeframes(b'\x00\x00' * 210000)
            with patch('backend.core.transcriber.require_provider_calls'), patch.dict('os.environ', {'SARVAM_API_KEY': 'test'}), patch('backend.core.transcriber._send_to_sarvam', side_effect=['first', 'second']):
                segments = transcribe_segments([f.name], 'hinglish')
            self.assertEqual([(s['start_ms'], s['end_ms'], s['timing_precision']) for s in segments], [(0, 25000, 'piece'), (25000, 26250, 'piece')])
