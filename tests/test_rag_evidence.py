import unittest
from unittest.mock import Mock, patch
from langchain_core.messages import AIMessage
from backend.core import rag_engine
from test_hybrid import doc


class EvidenceTests(unittest.TestCase):
    def test_whitespace_quote_abstains_without_returning_draft(self):
        result = rag_engine.validate_grounded_answer(
            {'answer': 'fabricated draft', 'abstained': False,
             'evidence': [{'chunk_id': 'a:000000', 'quote': ' '}]},
            [doc(0, 'Alice will ship Friday.')])
        self.assertEqual(result, {'answer': rag_engine.ABSTENTION, 'abstained': True, 'citations': []})

    def test_whitespace_answer_abstains_even_with_a_valid_quote(self):
        result = rag_engine.validate_grounded_answer(
            {'answer': '   ', 'abstained': False,
             'evidence': [{'chunk_id': 'a:000000', 'quote': 'ship Friday'}]},
            [doc(0, 'Alice will ship Friday.')])
        self.assertEqual(result, {'answer': rag_engine.ABSTENTION, 'abstained': True, 'citations': []})

    def test_unknown_ids_and_fabricated_quotes_abstain(self):
        self.assertTrue(hasattr(rag_engine,'validate_grounded_answer'),'grounded parser missing')
        docs=[doc(0,'Alice will ship Friday.')]
        for evidence in ([{'chunk_id':'b:000000','quote':'Alice'}],[{'chunk_id':'a:000000','quote':'Monday'}],[]):
            result=rag_engine.validate_grounded_answer({'answer':'A claim','abstained':False,'evidence':evidence},docs)
            self.assertTrue(result['abstained']); self.assertEqual(result['citations'],[])

    def test_valid_evidence_restores_server_timestamps(self):
        self.assertTrue(hasattr(rag_engine,'validate_grounded_answer'),'grounded parser missing')
        result=rag_engine.validate_grounded_answer({'answer':'Friday','abstained':False,'evidence':[{'chunk_id':'a:000000','quote':'ship Friday'}]},[doc(0,'Alice will ship Friday.')])
        self.assertEqual(result['citations'],[{'chunk_id':'a:000000','text':'ship Friday','start_ms':0,'end_ms':1000,'timing_precision':'segment'}])

    def test_empty_context_abstains_without_invoking_generation(self):
        with patch.object(rag_engine, 'hybrid_retrieve', return_value=([], {})), \
                patch.object(rag_engine, 'load_ranker'), patch.object(rag_engine, 'get_llm') as model:
            result = rag_engine._answer_question('question', 'a', 'economy', [], Mock())
        self.assertTrue(result['abstained'])
        model.assert_called_once_with(tier='economy')
        model.return_value.invoke.assert_not_called()
