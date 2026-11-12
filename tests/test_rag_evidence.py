import unittest
from unittest.mock import Mock, patch
from backend.core import rag_engine
from test_hybrid import doc

TEXT = 'Alice will ship the release on Friday after review.'


class EvidenceTests(unittest.TestCase):
    def test_whitespace_quote_abstains_without_returning_draft(self):
        result = rag_engine.validate_grounded_answer(
            {'answer': 'fabricated draft', 'abstained': False,
             'evidence': [{'chunk_id': 'a:000000', 'quote': ' '}]},
            [doc(0, TEXT)])
        self.assertEqual(result, {'answer': rag_engine.ABSTENTION, 'abstained': True, 'citations': []})

    def test_markdown_fenced_json_answer_is_accepted(self):
        raw = ('```json\n{"answer": "Alice ships Friday.", "abstained": false, '
               '"evidence": [{"chunk_id": "a:000000", "quote": "ship the release on Friday"}]}\n```')
        result = rag_engine.validate_grounded_answer(raw, [doc(0, TEXT)])
        self.assertFalse(result['abstained'])
        self.assertEqual(result['citations'][0]['text'], 'ship the release on Friday')

    def test_case_only_quote_mismatch_cites_transcript_wording(self):
        result = rag_engine.validate_grounded_answer(
            {'answer': 'Alice ships Friday.', 'abstained': False,
             'evidence': [{'chunk_id': 'a:000000', 'quote': 'alice will ship the release'}]},
            [doc(0, TEXT)])
        self.assertFalse(result['abstained'])
        self.assertEqual(result['citations'][0]['text'], 'Alice will ship the release')

    def test_chat_validator_rejects_bad_output_so_the_next_route_answers(self):
        docs = [doc(0, TEXT)]
        valid = '{"answer": "Friday.", "abstained": false, "evidence": [{"chunk_id": "a:000000", "quote": "ship the release on Friday"}]}'
        rag_engine._require_grounded(valid, docs)
        rag_engine._require_grounded('{"answer": "Not found.", "abstained": true, "evidence": []}', docs)
        for bad in ('Friday (a:000000)', '{"answer": "Monday.", "abstained": false, '
                    '"evidence": [{"chunk_id": "a:000000", "quote": "ship the release on Monday"}]}'):
            with self.assertRaises(ValueError):
                rag_engine._require_grounded(bad, docs)

    def test_whitespace_answer_abstains_even_with_a_valid_quote(self):
        result = rag_engine.validate_grounded_answer(
            {'answer': '   ', 'abstained': False,
             'evidence': [{'chunk_id': 'a:000000', 'quote': 'ship the release on Friday'}]},
            [doc(0, TEXT)])
        self.assertEqual(result, {'answer': rag_engine.ABSTENTION, 'abstained': True, 'citations': []})

    def test_unknown_ids_and_fabricated_quotes_abstain(self):
        self.assertTrue(hasattr(rag_engine,'validate_grounded_answer'),'grounded parser missing')
        docs=[doc(0,TEXT)]
        for evidence in ([{'chunk_id':'b:000000','quote':'Alice'}],[{'chunk_id':'a:000000','quote':'Monday'}],[]):
            result=rag_engine.validate_grounded_answer({'answer':'A claim','abstained':False,'evidence':evidence},docs)
            self.assertTrue(result['abstained']); self.assertEqual(result['citations'],[])

    def test_valid_evidence_restores_server_timestamps(self):
        self.assertTrue(hasattr(rag_engine,'validate_grounded_answer'),'grounded parser missing')
        result=rag_engine.validate_grounded_answer({'answer':'Friday','abstained':False,'evidence':[{'chunk_id':'a:000000','quote':'ship the release on Friday'}]},[doc(0,TEXT)])
        self.assertEqual(result['citations'],[{'chunk_id':'a:000000','text':'ship the release on Friday','start_ms':0,'end_ms':1000,'timing_precision':'segment'}])

    def test_trivial_or_partial_word_quotes_do_not_ground_answers(self):
        docs = [doc(0, TEXT)]
        for quote in ('the', 'Alice will', 'lice will ship the release', 'ship the release on Fri'):
            with self.subTest(quote=quote):
                result = rag_engine.validate_grounded_answer(
                    {'answer': 'Injected claim', 'abstained': False, 'evidence': [{'chunk_id': 'a:000000', 'quote': quote}]}, docs)
                self.assertTrue(result['abstained'])

    def test_quote_of_a_whole_short_chunk_is_accepted(self):
        result = rag_engine.validate_grounded_answer(
            {'answer': 'Yes.', 'abstained': False, 'evidence': [{'chunk_id': 'a:000000', 'quote': 'Budget approved.'}]},
            [doc(0, 'Budget approved.')])
        self.assertEqual(result['citations'][0]['text'], 'Budget approved.')

    def test_empty_context_abstains_without_invoking_generation(self):
        with patch.object(rag_engine, 'hybrid_retrieve', return_value=([], {})), \
                patch.object(rag_engine, 'load_ranker'), patch.object(rag_engine, 'get_llm') as model:
            result = rag_engine._answer_question('question', 'a', 'economy', [], Mock())
        self.assertTrue(result['abstained'])
        model.assert_called_once_with(tier='economy', task='chat')
        model.return_value.invoke.assert_not_called()
