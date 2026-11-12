import os
import unittest
from pathlib import Path
from unittest.mock import patch
from langchain_core.documents import Document
from backend.core import vector_store


def doc(i, text, job='a'):
    return Document(id=f'{job}:{i:06d}', page_content=text, metadata={'job_id':job,'ordinal':i,'chunk_index':i,'chunk_id':f'{job}:{i:06d}','start_ms':i*1000,'end_ms':(i+1)*1000,'timing_precision':'segment'})


class HybridTests(unittest.TestCase):
    def test_rrf_deduplicates_and_ties_by_ordinal(self):
        from backend.core.retrieval import reciprocal_rank_fusion
        a,b,c=doc(0,'a'),doc(1,'b'),doc(2,'c')
        result=reciprocal_rank_fusion([[b,a],[a,b,c]])
        self.assertEqual([x.metadata['chunk_id'] for x in result], ['a:000000','a:000001','a:000002'])

    def test_sparse_excludes_no_overlap_and_normalizes_unicode(self):
        from backend.core.retrieval import sparse_candidates
        docs=[doc(0,'ＡＰＩ launch'),doc(1,'Budget allocation'),doc(2,'scheduling')]
        self.assertEqual([d.id for d in sparse_candidates(docs,'api')],['a:000000'])
        self.assertEqual(sparse_candidates(docs,'missing'),[])

    def test_sparse_retains_matching_terms_with_negative_bm25_idf(self):
        from backend.core.retrieval import sparse_candidates
        self.assertEqual([d.id for d in sparse_candidates([doc(0,'release Friday')],'release')],['a:000000'])
        self.assertEqual(sparse_candidates([doc(0,'!!!')],'release'),[])
        self.assertEqual([d.id for d in sparse_candidates([doc(0,'release Friday'),doc(1,'budget Monday')],'release')],['a:000000'])

    def test_foreign_dense_id_fails_before_reranking(self):
        from backend.core.retrieval import hybrid_retrieve, RetrievalUnavailable
        from unittest.mock import Mock
        store=Mock()
        store.similarity_search.return_value=[doc(0,'foreign','b')]
        with patch('backend.core.retrieval.rerank_documents') as rerank:
            with self.assertRaises(RetrievalUnavailable):
                hybrid_retrieve('api','a',[doc(0,'api')],store)
            rerank.assert_not_called()

    def test_hydration_uses_owned_text_and_required_reranker(self):
        from backend.core.retrieval import hybrid_retrieve, RetrievalUnavailable
        from unittest.mock import Mock
        store=Mock(); store.similarity_search.return_value=[doc(0,'untrusted stale vector text')]
        with patch('backend.core.retrieval.rerank_documents',return_value=([doc(0,'real text')],{'truncated':False})) as rerank:
            docs,meta=hybrid_retrieve('real','a',[doc(0,'real text')],store)
            self.assertEqual(rerank.call_args.args[1][0].page_content,'real text')
            self.assertEqual(meta['dense_count'],1)
        with patch('backend.core.retrieval.rerank_documents',side_effect=RuntimeError('bad')):
            with self.assertRaises(RetrievalUnavailable):
                hybrid_retrieve('real','a',[doc(0,'real text')],store)

    def test_embedding_vector_is_finite_normalized_and_dimension_checked(self):
        from backend.core.embedding_routes import normalize_embedding
        vector=normalize_embedding([3.0,4.0]+[0.0]*766, 768)
        self.assertEqual(vector[:2],[0.6,0.8])
        for invalid in ([0.0]*768,[float('nan')]*768,[1.0]*767):
            with self.assertRaises(ValueError): normalize_embedding(invalid, 768)

    def test_corrupt_raw_corpus_is_sanitized_and_empty_reranker_is_unavailable(self):
        from backend.core.retrieval import hybrid_retrieve, RetrievalUnavailable
        from unittest.mock import Mock
        store=Mock();store.similarity_search.return_value=[doc(0,'alice@example.com')]
        with patch('backend.core.retrieval.rerank_documents',return_value=([],{})) as rerank:
            with self.assertRaises(RetrievalUnavailable):
                hybrid_retrieve('alice@example.com','a',[doc(0,'alice@example.com')],store)
            self.assertNotIn('alice@example.com',store.similarity_search.call_args.args[0])
            self.assertNotIn('alice@example.com',rerank.call_args.args[1][0].page_content)

    def test_reranker_rejects_unbounded_candidate_batches_before_model_load(self):
        from backend.core.reranker import rerank_documents
        from backend.core.retrieval import RetrievalUnavailable
        with patch('backend.core.reranker.load_ranker') as loader:
            with self.assertRaises(RetrievalUnavailable): rerank_documents('q',[doc(i,'text') for i in range(13)])
            loader.assert_not_called()

    def test_missing_local_model_fails_without_download(self):
        from backend.core.reranker import load_ranker
        from backend.core.retrieval import RetrievalUnavailable
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'RERANK_MODEL_DIR':directory}):
            with self.assertRaises(RetrievalUnavailable): load_ranker()

    def test_embedding_query_redacts_before_http_and_records_failure_without_retry(self):
        from backend.core.llm_gateway import operation_scope
        env={'ENABLE_PROVIDER_CALLS':'true','RATE_LIMIT_SECRET':'x'*32,'ENABLE_GEMINI_EMBEDDINGS':'true',
             'GEMINI_EMBEDDINGS_VERIFIED_FREE':'true','GEMINI_API_KEY':'offline','GEMINI_EMBEDDINGS_RPM':'10',
             'GEMINI_EMBEDDINGS_TPM':'50000','GEMINI_EMBEDDINGS_RPD':'100'}
        with patch.dict(os.environ,env,clear=True),patch('backend.core.embedding_routes.httpx.Client') as client, \
                patch.object(vector_store.provider_budget,'reserve_attempt',return_value=7), \
                patch.object(vector_store.provider_budget,'record_attempt_result') as record,operation_scope('a'):
            client.return_value.__enter__.return_value.post.return_value.json.return_value={'embeddings':[{'values':[1.0]*767}]}
            with self.assertRaises(RuntimeError):vector_store.get_embeddings().embed_query('Email alice@example.com')
            post=client.return_value.__enter__.return_value.post
            self.assertEqual(post.call_count,1)
            request=post.call_args.kwargs['json']['requests'][0]
            self.assertNotIn('alice@example.com',request['content']['parts'][0]['text'])
            self.assertEqual(request['taskType'],'RETRIEVAL_QUERY')
            self.assertEqual(request['outputDimensionality'],768)
            self.assertEqual(record.call_args.args[:2],(7,'failed'))

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'backend/model_assets/ms-marco-TinyBERT-L-2-v2').is_dir(), 'prepare pinned local reranker assets')
    def test_real_local_reranker_reuses_session_and_restores_full_text(self):
        from backend.core.reranker import load_ranker, rerank_documents
        documents=[doc(0,'Friday release. '+('project details '*700)),doc(1,'The budget is Monday.')]
        ranker=load_ranker()
        with patch.object(ranker,'_download_model_files',side_effect=AssertionError('runtime downloads forbidden')):
            result,meta=rerank_documents('When is the release?',documents)
        self.assertIs(ranker,load_ranker())
        self.assertTrue(meta['truncated'])
        self.assertEqual({item.id for item in result},{'a:000000','a:000001'})
        self.assertEqual(next(item.page_content for item in result if item.id=='a:000000'),documents[0].page_content)
        self.assertEqual(len(meta['scores']),2)
