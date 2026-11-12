import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from backend.core import embedding_routes, extractor, rag_engine, summarizer, transcriber, vector_store
from backend.core.llm_gateway import operation_scope


class ProviderGuardsTests(unittest.TestCase):
    def test_disabled_guard_covers_all_provider_factories(self):
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'false'}):
            for operation in (summarizer.get_llm, extractor.get_llm, rag_engine.get_llm,
                              vector_store.get_embeddings,
                              lambda: transcriber.transcribe_chunk_groq('missing'),
                              lambda: transcriber._send_to_sarvam('missing'),
                              lambda: transcriber.transcribe_chunk_sarvam('missing')):
                with self.subTest(operation=operation), self.assertRaises(RuntimeError):
                    operation()

    def test_transcript_length_is_rejected_without_truncation(self):
        with patch.object(transcriber, '_wav_duration_ms', return_value=1000), patch.object(transcriber, '_groq_segments', side_effect=[
                [{'text': 'a' * 20000, 'start': 0, 'end': 1}],
                [{'text': 'b' * 20001, 'start': 0, 'end': 1}]]):
            with self.assertRaises(ValueError):
                transcriber.transcribe_all(['one', 'two'])

    def test_embeddings_are_bounded_without_hidden_retries(self):
        env = {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 'x' * 32,
               'ENABLE_GEMINI_EMBEDDINGS': 'true', 'GEMINI_EMBEDDINGS_VERIFIED_FREE': 'true',
               'GEMINI_API_KEY': 'offline-placeholder', 'GEMINI_EMBEDDINGS_RPM': '10',
               'GEMINI_EMBEDDINGS_TPM': '50000', 'GEMINI_EMBEDDINGS_RPD': '100'}
        with patch.dict(os.environ, env, clear=True), patch.object(embedding_routes.httpx, 'Client') as client, \
                patch.object(embedding_routes.httpx, 'HTTPTransport') as transport, \
                patch('backend.core.provider_budget.reserve_attempt'), \
                patch('backend.core.provider_budget.record_attempt_result'), operation_scope('test-job'):
            client.return_value.__enter__.return_value.post.return_value.json.return_value = {
                'embeddings': [{'values': [1.0] + [0.0] * 767}]}
            result = vector_store.get_embeddings().embed_query('Question')
            self.assertEqual(result, [1.0] + [0.0] * 767)
            self.assertEqual(client.call_args.kwargs['timeout'], 60)
            self.assertFalse(client.call_args.kwargs['trust_env'])
            self.assertEqual(transport.call_args.kwargs['retries'], 0)

    def test_delete_collection_requires_no_provider_and_uses_parameterized_name(self):
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'false'}), \
                patch('backend.db.connect') as connect, \
                patch.object(vector_store, 'get_embeddings') as embeddings:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = {'table_name': 'langchain_pg_collection'}
            vector_store.db.delete_vector_store('abc')
            embeddings.assert_not_called()
            deletes = [call.args for call in cursor.execute.call_args_list if call.args[0].startswith('DELETE')]
            self.assertEqual(deletes, [('DELETE FROM langchain_pg_collection WHERE name=%s', ('job_abc',)),
                                       ('DELETE FROM transcript_chunks WHERE job_id=%s', ('abc',))])

    def test_delete_collection_is_noop_when_table_absent(self):
        with patch('backend.db.connect') as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = {'table_name': None}
            vector_store.db.delete_vector_store('abc')
            self.assertEqual(cursor.execute.call_count, 2)
            self.assertFalse(any(call.args[0].startswith('DELETE') for call in cursor.execute.call_args_list))

    def test_oversized_context_rejected_before_model_or_embedding(self):
        operations = (summarizer.summarize, summarizer.generate_title,
                      extractor.extract_action_items, extractor.extract_key_decisions,
                      extractor.extract_questions, lambda text: vector_store.build_vector_store(text, 'job'),
                      lambda text: rag_engine.build_rag_chain(text, 'job'))
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                operation('x' * 40001)

    def test_exact_transcript_boundary_is_accepted(self):
        with patch.object(transcriber, '_wav_duration_ms', return_value=1000), \
                patch.object(transcriber, '_groq_segments', return_value=[{'text': 'a' * 40000, 'start': 0, 'end': 1}]):
            self.assertEqual(len(transcriber.transcribe_all(['one'])), 40000)

    def _sample_wav(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = str(Path(directory) / 'audio.wav')
        with wave.open(path, 'wb') as handle:
            handle.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            handle.writeframes(b'\x00\x00' * 8000)
        return path

    def _stt_env(self, provider, model, keyenv):
        profile = {'provider': provider, 'model': model, 'keyenv': keyenv, 'verified_free': True,
                   'rpm': 10, 'rpd': 100, 'audio_seconds_hour': 600, 'audio_seconds_day': 3600}
        return {'ENABLE_PROVIDER_CALLS': 'true', 'ENABLE_SARVAM': 'true', 'RATE_LIMIT_SECRET': 'x' * 32,
                keyenv: 'offline-placeholder', 'STT_PROFILES_JSON': json.dumps([profile])}

    def test_groq_client_is_bounded_and_model_resolved_at_call(self):
        model = 'whisper-large-v3-turbo'
        path = self._sample_wav()
        with patch.dict(os.environ, self._stt_env('groq', model, 'GROQ_API_KEY'), clear=True), \
                patch.object(transcriber, 'Groq') as groq, \
                patch.object(transcriber.audio_budget, 'reserve_audio_attempt') as reserve, operation_scope('test-job'):
            create = groq.return_value.audio.transcriptions.create
            create.return_value = {'segments': [{'text': 'text', 'start': 0, 'end': 1}]}
            self.assertEqual(transcriber.transcribe_chunk_groq(path), 'text')
            self.assertEqual(groq.call_args.kwargs['timeout'], 60)
            self.assertEqual(groq.call_args.kwargs['max_retries'], 0)
            self.assertEqual(create.call_args.kwargs['model'], model)
            self.assertEqual(create.call_args.kwargs['timestamp_granularities'], ['segment'])
            self.assertEqual(reserve.call_args.args[0], 'test-job')
            self.assertEqual(reserve.call_args.args[2], 1000)

    def test_sarvam_key_and_model_resolved_at_call(self):
        model = 'saaras:v2.5'
        path = self._sample_wav()
        with patch.dict(os.environ, self._stt_env('sarvam', model, 'SARVAM_API_KEY'), clear=True), \
                patch.object(transcriber.requests, 'post') as post, \
                patch.object(transcriber.audio_budget, 'reserve_audio_attempt') as reserve, operation_scope('test-job'):
            post.return_value.ok = True
            post.return_value.json.return_value = {'transcript': 'text'}
            self.assertEqual(transcriber._send_to_sarvam(path), 'text')
            self.assertEqual(post.call_args.kwargs['headers']['api-subscription-key'], 'offline-placeholder')
            self.assertEqual(post.call_args.kwargs['data']['model'], model)
            self.assertEqual(post.call_args.kwargs['timeout'], 120)
            self.assertEqual(reserve.call_args.args[0], 'test-job')
            self.assertEqual(reserve.call_args.args[2], 1000)

    def test_unverified_stt_never_reserves_or_constructs_a_remote_client(self):
        env = {'ENABLE_PROVIDER_CALLS': 'true', 'ENABLE_SARVAM': 'true', 'RATE_LIMIT_SECRET': 'x' * 32,
               'GROQ_API_KEY': 'offline-placeholder', 'SARVAM_API_KEY': 'offline-placeholder'}
        with patch.dict(os.environ, env, clear=True), patch.object(transcriber, 'Groq') as groq, \
                patch.object(transcriber.requests, 'post') as post, \
                patch.object(transcriber.audio_budget, 'reserve_audio_attempt') as reserve, operation_scope('test-job'):
            for transcribe in (transcriber.transcribe_chunk_groq, transcriber._send_to_sarvam):
                with self.subTest(transcribe=transcribe), self.assertRaises(ValueError):
                    transcribe('missing')
        groq.assert_not_called()
        post.assert_not_called()
        reserve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
