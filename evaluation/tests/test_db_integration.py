"""Opt-in: index + answer through the real app code against a disposable loopback pgvector database.

Providers are faked at the HTTP transport (embeddings) and at llm_gateway._invoke_route (generation),
so the app's own budget reservations, pgvector writes, hybrid retrieval and reranker all run for real.
Set EVAL_TEST_DATABASE_URL to a throwaway database named ava_eval (never the run database).
"""
import hashlib
import json
import math
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage

from evaluation.dataset import validate
from evaluation.runners import adapter, guards

URL = os.getenv('EVAL_TEST_DATABASE_URL')
ROUTE = dict(alias='gemini-flash', tier='economy', provider='gemini', model='gemini/gemini-2.5-flash',
             api_key_env='GEMINI_API_KEY', verified_free=True, input_limit_tokens=20000, rpm=1000, tpm=10_000_000, rpd=1000)
ENV = {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32, 'GEMINI_API_KEY': 'offline-placeholder',
       'LLM_ROUTES_JSON': json.dumps([ROUTE]),
       'EMBEDDING_ROUTES_JSON': json.dumps([{'id': 'gemini-embeddings', 'verified_free': True,
                                             'rpm': 1000, 'tpm': 10_000_000, 'rpd': 1000}]),
       'ENABLE_PAID_META': 'false', 'ENABLE_PUBLIC_PAID_FALLBACK': 'false'}


def bag_of_words(text, dimension=768):
    vector = [0.0] * dimension
    for word in text.lower().split():
        vector[int(hashlib.sha256(word.strip('.,!?').encode()).hexdigest(), 16) % dimension] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def fake_transport(self, request):
    if request.url.host != 'generativelanguage.googleapis.com' or not request.url.path.endswith(':batchEmbedContents'):
        raise AssertionError(f'unexpected network call to {request.url.host}')
    body = json.loads(request.content)
    embeddings = [{'values': bag_of_words(r['content']['parts'][0]['text'])} for r in body['requests']]
    return httpx.Response(200, json={'embeddings': embeddings}, request=request)


def fake_generation(route, messages, *args, **kwargs):
    evidence = json.loads(messages[-1].content)['evidence']
    quote = ' '.join(evidence[0]['text'].split()[2:10])
    content = json.dumps({'answer': 'Grounded test answer.', 'abstained': False,
                          'evidence': [{'chunk_id': evidence[0]['chunk_id'], 'quote': quote}]})
    return AIMessage(content=content, response_metadata={'finish_reason': 'stop'},
                     usage_metadata={'input_tokens': 500, 'output_tokens': 60, 'total_tokens': 560})


@unittest.skipUnless(URL, 'requires EVAL_TEST_DATABASE_URL (disposable loopback pgvector named ava_eval)')
class AdapterDatabaseTests(unittest.TestCase):
    def test_index_answer_and_resume_through_real_app_code(self):
        from backend import db
        guards.require_eval_database(URL)
        job_id = uuid.uuid4().hex
        tmp = Path(tempfile.mkdtemp())
        goldens = [json.loads(line) for line in validate.RESOLVED_FILE.read_text().splitlines()][:3]
        with patch.dict(os.environ, {**ENV, 'DATABASE_URL': URL}), \
                patch('httpx.HTTPTransport.handle_request', fake_transport), \
                patch('backend.core.llm_gateway._invoke_route', side_effect=fake_generation):
            try:
                indexed = adapter.index(job_id)
                self.assertEqual((indexed['status'], indexed['chunks']), ('indexed', 22))
                self.assertEqual(adapter.index(job_id)['status'], 'already_indexed')
                run = adapter.answer_all(goldens, scope='public', job_id=job_id, out_dir=tmp / 'answers',
                                         cache_path=tmp / 'cache.json', progress=lambda _: None)
                self.assertIsNone(run['stopped_early'])
                self.assertEqual(run['embedding']['batch_requests'][0]['texts'], 3)
                self.assertEqual(run['embedding']['cache'], {'hits': 3, 'misses': 0})
                answers = adapter.load_answers(tmp / 'answers')
                self.assertEqual(sorted(answers), sorted(g['id'] for g in goldens))
                for case in answers.values():
                    self.assertIsNone(case['error'])
                    self.assertFalse(case['result']['abstained'])
                    self.assertEqual(len(case['contexts']['final']), 4)
                    self.assertTrue(case['contexts']['fused'])
                    self.assertEqual(case['calls'][0]['provider'], 'gemini')
                    self.assertTrue({s['stage'] for s in case['stages']} >= {'dense_retrieval', 'sparse_retrieval', 'rrf', 'rerank'})
                # Resume: nothing is re-asked.
                again = adapter.answer_all(goldens, scope='public', job_id=job_id, out_dir=tmp / 'answers',
                                           cache_path=tmp / 'cache.json', progress=lambda _: None)
                self.assertEqual(again['cases'], [])
            finally:
                db.delete_vector_store(job_id)
                with db.connect() as conn:
                    conn.execute('DELETE FROM jobs WHERE id=%s', (job_id,))
                    for table in ('provider_attempts', 'provider_operation_budgets'):
                        conn.execute(f'DELETE FROM {table} WHERE job_id=%s', (job_id,))


if __name__ == '__main__':
    unittest.main()
