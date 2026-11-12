import logging
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from langchain_core.documents import Document
from backend.core import telemetry
from backend.core.retrieval import hybrid_retrieve
from backend.core.transcriber import transcribe_segments
from stt_fixture import groq_chain


class TelemetryTests(unittest.TestCase):
    def test_stage_failure_logs_no_exception_and_logging_failure_is_ignored(self):
        with self.assertLogs('uvicorn.error.metrics', logging.INFO) as logs:
            with self.assertRaisesRegex(RuntimeError, 'secret'):
                with telemetry.duration('safe_stage'):
                    raise RuntimeError('secret')
        self.assertIn('status=failed', logs.output[0])
        self.assertNotIn('secret', logs.output[0])
        with patch.object(telemetry.logger, 'info', side_effect=RuntimeError('logging broken')):
            with telemetry.duration('safe_stage'):
                pass

    def test_retrieval_and_transcription_do_not_log_private_content(self):
        self.enterContext(groq_chain())
        secret = 'alice@example.com'
        doc = Document(id='job:0', page_content=secret, metadata={'job_id': 'job', 'ordinal': 0, 'chunk_id': 'job:0'})
        store = Mock()
        store.similarity_search.return_value = [doc]
        with self.assertLogs('uvicorn.error.metrics', logging.INFO) as logs, \
                patch('backend.core.retrieval.rerank_documents', return_value=([doc], {})), \
                patch('backend.core.transcriber._wav_duration_ms', return_value=1000), \
                patch('backend.core.transcriber._groq_segments', return_value=[{'text': secret, 'start': 0, 'end': 1}]):
            hybrid_retrieve(secret, 'job', [doc], store)
            transcribe_segments(['/secret/path.wav'])
        output = '\n'.join(logs.output)
        for stage in ('dense_retrieval', 'sparse_retrieval', 'rrf', 'rerank', 'stt_chunk'):
            self.assertIn(stage, output)
        self.assertNotIn(secret, output)
        self.assertNotIn('/secret/path.wav', output)
        self.assertNotIn('job:0', output)

    def test_media_sizes_are_local_and_cleanup_logs_no_path(self):
        from backend.utils import audio_processor
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, 'private-source')
            chunk = os.path.join(directory, 'private-audio.wav')
            with open(source, 'wb') as file:
                file.write(b'123')
            with open(chunk, 'wb') as file:
                file.write(b'12345')
            with self.assertLogs('uvicorn.error.metrics', logging.INFO) as logs, \
                    patch.object(audio_processor, 'chunk_streaming', return_value=([chunk], directory)):
                audio_processor.process_input(source)
            output = '\n'.join(logs.output)
            self.assertIn('local_file_bytes=3', output)
            self.assertIn('wav_file_bytes=5', output)
            self.assertIn('audio_conversion', output)
            self.assertNotIn(directory, output)
            with self.assertLogs('uvicorn.error.metrics', logging.INFO) as logs, \
                    patch.object(audio_processor.os, 'remove', side_effect=OSError('private-error')), \
                    patch.object(audio_processor.shutil, 'rmtree', side_effect=OSError('private-dir-error')):
                audio_processor.cleanup([chunk, directory])
            self.assertEqual(len(logs.output), 2)
            for entry in logs.output:
                self.assertIn('metric=audio_cleanup status=failed', entry)
                self.assertNotIn('private', entry)
