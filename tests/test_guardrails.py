import unittest
from backend.core.guardrails import sanitize_text
from backend.core.chunks import prepare_documents

class GuardrailsTests(unittest.TestCase):
    def test_credential_formats_preserve_offsets_and_hide_complete_values(self):
        for text, secret in [
            ('Authorization: Bearer demo-token-123', 'demo-token-123'),
            ('{"password":"DemoPassword123!"}', 'DemoPassword123!'),
            ('password="two word secret"', 'two word secret'),
            ('sk-proj-abcdefghijklmnopqrstuvwx', 'sk-proj-abcdefghijklmnopqrstuvwx'),
        ]:
            with self.subTest(text=text):
                result = sanitize_text(text)
                self.assertEqual(len(result), len(text))
                self.assertNotIn(secret, result)
                self.assertNotIn(secret.split()[-1], result)

    def test_authorization_basic_and_bearer_values_are_redacted(self):
        for text in ('Authorization: Basic dXNlcjpwYXNzd29yZA==', 'Authorization: Bearer token-value', '{"Authorization": "Basic dXNlcjpwYXNzd29yZA=="}', '{"Authorization": "Bearer token-value"}'):
            with self.subTest(text=text):
                result = sanitize_text(text)
                self.assertEqual(len(result), len(text))
                self.assertNotIn('dXNlcjpwYXNzd29yZA==', result)
                self.assertNotIn('token-value', result)
                self.assertNotIn('Basic', result)
                self.assertNotIn('Bearer', result)

    def test_sensitive_data_and_benign_details(self):
        text = 'Alice on 2026-11-05 paid 1200. Contact alice@example.com or +91 98765 43210 / 9876543210. Card 4111 1111 1111 1111. api_key=sk-secret123456789'
        result = sanitize_text(text)
        for secret in ('alice@example.com', '98765 43210', '9876543210', '4111 1111 1111 1111', 'sk-secret123456789'):
            self.assertNotIn(secret, result)
        for benign in ('Alice', '2026-11-05', '1200'):
            self.assertIn(benign, result)

    def test_cross_segment_pii_is_redacted_before_chunking(self):
        segments = [{'text': 'Email alice@', 'start_ms': 0, 'end_ms': 1000, 'timing_precision': 'segment'}, {'text': 'example.com now', 'start_ms': 1000, 'end_ms': 2000, 'timing_precision': 'segment'}]
        docs = prepare_documents(segments, 'job')
        self.assertNotIn('alice@', ''.join(d.page_content for d in docs))
        self.assertEqual(docs[0].metadata['chunk_id'], 'job:000000')
        self.assertEqual(docs[0].id, 'job:000000')
        self.assertEqual(docs[0].metadata['end_ms'], 2000)

    def test_job_persists_only_sanitized_transcript_and_chunks(self):
        from contextlib import nullcontext
        from unittest.mock import patch
        from backend import jobs
        segment = {'text': 'email alice@example.com', 'start_ms': 0, 'end_ms': 1000, 'timing_precision': 'segment'}
        with patch.object(jobs, 'require_provider_calls'), patch.object(jobs, 'process_input', return_value=(['audio'], [])), patch.object(jobs, 'transcribe_segments', return_value=[segment]), patch.object(jobs, 'operation_scope', return_value=nullcontext()), patch.object(jobs.db, 'set_step'), patch.object(jobs.db, 'finish_job') as finish, patch.object(jobs, 'preflight_processing') as preflight, patch.object(jobs, 'generate_title', return_value='title'), patch.object(jobs, 'summarize', return_value='summary'), patch.object(jobs, 'extract_findings', return_value={'action_items': '', 'key_decisions': '', 'open_questions': ''}), patch.object(jobs, 'build_rag_chain') as build, patch.object(jobs, 'cleanup'):
            jobs.run_job('job', 'source')
        self.assertNotIn('alice@example.com', preflight.call_args.args[0])
        self.assertNotIn('alice@example.com', finish.call_args.args[1]['transcript'])
        self.assertNotIn('alice@example.com', build.call_args.kwargs['documents'][0].page_content)

    def test_common_tokens_and_benign_numbers(self):
        for secret in ('sk-proj-abcdefghijklmnopqrstuvwx', '4222222222222', '9876543210'):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, sanitize_text(f'value {secret}'))
        for value in ('Alice Smith', '2026-11-05', 'paid 1200', 'Order 123456789'):
            with self.subTest(value=value):
                self.assertIn(value, sanitize_text(value))

    def test_standalone_configured_provider_key_formats_are_redacted(self):
        for key in ('gsk_' + 'a' * 52, 'AIza' + 'z' * 35, 'nvapi-' + 'x' * 43, 'sk-or-v1-' + 'f' * 64):
            with self.subTest(prefix=key[:4]):
                text = 'Use ' + key + ' tomorrow.'
                self.assertEqual(sanitize_text(text), 'Use ' + '█' * len(key) + ' tomorrow.')

    def test_cross_segment_card_and_phone(self):
        for parts, secret in [(['Card 4111 1111', '1111 1111'], '4111 1111'), (['Call +91 98765', '43210 now'], '98765')]:
            with self.subTest(parts=parts):
                segments = [{'text': part, 'start_ms': i * 1000, 'end_ms': (i + 1) * 1000, 'timing_precision': 'segment'} for i, part in enumerate(parts)]
                result = ' '.join(doc.page_content for doc in prepare_documents(segments, 'job'))
                self.assertNotIn(secret, result)
