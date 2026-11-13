"""Offline tests for the evaluation framework: no network, no database, no provider or judge calls."""
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('DEEPEVAL_DISABLE_DOTENV', '1')
os.environ.setdefault('DEEPEVAL_TELEMETRY_OPT_OUT', 'YES')

from evaluation import config  # noqa: E402
from evaluation.dataset import build_chunks, validate  # noqa: E402
from evaluation.metrics import deepeval_suite, deterministic, ir, judge, registry  # noqa: E402
from evaluation.runners import adapter, experiments, guards, report  # noqa: E402

SEGMENTS = build_chunks.load_segments()
DOCUMENTS = build_chunks.build_documents(SEGMENTS)
RESOLVED = [json.loads(line) for line in validate.RESOLVED_FILE.read_text().splitlines()]
BY_ID = {g['id']: g for g in RESOLVED}
FAKE_KEY = 'mk-test-0123456789abcdef'  # gitleaks:allow (fake test value)


def chunk(doc):
    return {'chunk_id': doc.metadata['chunk_id'], 'text': doc.page_content,
            'start_ms': doc.metadata['start_ms'], 'end_ms': doc.metadata['end_ms']}


def citation(doc, text):
    return {'chunk_id': doc.metadata['chunk_id'], 'text': text, 'start_ms': doc.metadata['start_ms'],
            'end_ms': doc.metadata['end_ms'], 'timing_precision': doc.metadata['timing_precision']}


def answered(golden, doc, quote, answer='NASA has 23 satellites.'):
    return {'answer': answer, 'abstained': False, 'citations': [citation(doc, quote)],
            'retrieval': {'chunk_ids': [doc.metadata['chunk_id']]}, 'model': {'tier': 'economy'}}


def abstained():
    from backend.core.rag_engine import ABSTENTION
    return {'answer': ABSTENTION, 'abstained': True, 'citations': [], 'retrieval': {}, 'model': {'tier': 'economy'}}


def captured_case(golden_id='NASA-F-001', result=None):
    golden = BY_ID[golden_id]
    doc = DOCUMENTS[0]
    result = result or answered(golden, doc, 'NASA has 23 satellites looking down at our Earth system')
    return {'golden': golden, 'result': result, 'error': None, 'scope': 'public', 'cold': False, 'e2e_ms': 1200,
            'calls': [{'alias': 'gemini-flash', 'provider': 'gemini', 'model': 'gemini/gemini-2.5-flash', 'ok': True,
                       'elapsed_ms': 900, 'raw_output': '{}'}],
            'stages': [{'stage': s, 'status': 'success', 'elapsed_ms': 5} for s in ('dense_retrieval', 'sparse_retrieval', 'rrf', 'rerank')],
            'contexts': {'final': [chunk(doc)], 'fused': [chunk(d) for d in DOCUMENTS[:3]],
                         'dense_ranking': [d.metadata['chunk_id'] for d in DOCUMENTS[:3]],
                         'sparse_ranking': [DOCUMENTS[2].metadata['chunk_id'], doc.metadata['chunk_id']],
                         'fused_ranking': [d.metadata['chunk_id'] for d in DOCUMENTS[:3]],
                         'final_ranking': [doc.metadata['chunk_id']],
                         'reranked_ranking': [doc.metadata['chunk_id'], DOCUMENTS[1].metadata['chunk_id']],
                         'reranker': {'truncated_count': 0}}}


class FakeCompletions:
    def __init__(self, content='{"verdict": "ok"}', error=None, usage=(100, 50)):
        self.content, self.error, self.usage, self.calls = content, error, usage, []

    def create(self, **options):
        self.calls.append(options)
        if self.error:
            raise self.error
        usage = SimpleNamespace(prompt_tokens=self.usage[0], completion_tokens=self.usage[1], completion_tokens_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))], usage=usage)


def fake_client(**kwargs):
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(**kwargs)))


class DatasetTests(unittest.TestCase):
    def test_goldens_load_and_resolve_without_errors(self):
        resolved, errors = validate.resolve(validate.load_goldens(), SEGMENTS, DOCUMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(len(resolved), sum(config.CATEGORY_COUNTS.values()))

    def test_resolved_file_is_current(self):
        self.assertEqual(validate.main(['--check']), 0)

    def test_every_answerable_quote_is_an_exact_substring_of_a_gold_chunk(self):
        texts = {d.metadata['chunk_id']: d.page_content for d in DOCUMENTS}
        for g in RESOLVED:
            for e in g['evidence']:
                self.assertTrue(e['chunk_ids'])
                self.assertTrue(all(e['quote'] in texts[c] for c in e['chunk_ids']))

    def test_fabricated_or_paraphrased_evidence_is_rejected(self):
        golden = validate.load_goldens()[0].model_copy(update={'expected_evidence': ['NASA has 24 satellites looking down']})
        _, errors = validate.resolve([golden], SEGMENTS, DOCUMENTS)
        self.assertTrue(any('not an exact substring' in e for e in errors))

    def test_unanswerable_absent_terms_must_be_absent(self):
        golden = next(g for g in validate.load_goldens() if g.category == 'unanswerable').model_copy(update={'absent_terms': ['methane']})
        _, errors = validate.resolve([golden], SEGMENTS, DOCUMENTS)
        self.assertTrue(any("absent term 'methane'" in e for e in errors))

    def test_unknown_fields_are_rejected(self):
        line = json.dumps({**json.loads(validate.GOLDENS_FILE.read_text().splitlines()[0]), 'surprise': 1})
        with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as handle:
            handle.write(line + '\n')
        with self.assertRaises(ValueError):
            validate.load_goldens(handle.name)
        os.unlink(handle.name)

    def test_source_checksum_is_enforced(self):
        with self.assertRaises(ValueError):
            build_chunks.load_segments(sha256='0' * 64)


class TestCaseConstructionTests(unittest.TestCase):
    def test_generation_case_uses_captured_answer_and_final_context(self):
        case = captured_case()
        tc = deepeval_suite.build_test_case(case, 'generation')
        self.assertEqual(tc.input, case['golden']['question'])
        self.assertEqual(tc.actual_output, case['result']['answer'])
        self.assertEqual(tc.expected_output, case['golden']['expected_answer'])
        self.assertEqual(tc.retrieval_context, [c['text'] for c in case['contexts']['final']])

    def test_pre_rerank_case_uses_fused_order(self):
        case = captured_case()
        tc = deepeval_suite.build_test_case(case, 'retrieval_pre_rerank')
        self.assertEqual(tc.retrieval_context, [c['text'] for c in case['contexts']['fused']])

    def test_no_context_means_no_test_case(self):
        case = captured_case()
        case['contexts']['final'] = []
        self.assertIsNone(deepeval_suite.build_test_case(case, 'generation'))

    def test_only_answerable_categories_with_results_are_eligible(self):
        self.assertTrue(deepeval_suite.eligible(captured_case()))
        self.assertFalse(deepeval_suite.eligible(captured_case('NASA-U-001', abstained())))
        self.assertFalse(deepeval_suite.eligible({**captured_case(), 'result': None}))


class MetricConfigTests(unittest.TestCase):
    def test_metrics_use_judge_thresholds_reasons_and_llm_mode(self):
        meta = judge.MetaJudge(judge.SpendLedger(1, path=Path(tempfile.mkdtemp()) / 'l.json'), client=fake_client())
        metrics = deepeval_suite.build_metrics(meta, config.GENERATION_METRICS)
        self.assertEqual([m.__name__ for m in metrics], list(config.GENERATION_METRICS))
        for m in metrics:
            self.assertIs(m.model, meta)
            self.assertEqual(m.threshold, config.THRESHOLDS[m.__name__])
            self.assertTrue(m.include_reason)
            self.assertEqual(str(getattr(m.eval_mode, 'value', m.eval_mode)), 'llm')

    def test_cases_dropped_by_deepeval_are_recorded_not_lost(self):
        from evaluation.runners import judge_runner
        meta = judge.MetaJudge(judge.SpendLedger(1, path=Path(tempfile.mkdtemp()) / 'l.json'), client=fake_client())
        one = SimpleNamespace(test_results=[SimpleNamespace(name='NASA-F-001:generation', success=True, metrics_data=[])])
        cases = [captured_case('NASA-F-001'), captured_case('NASA-F-002')]
        with patch.object(judge_runner, 'evaluate', return_value=one):
            rows = judge_runner.judge_stage(cases, 'generation', meta)
        missing = [r for r in rows if r.get('missing')]
        self.assertEqual([r['name'] for r in missing], ['NASA-F-002:generation'])
        self.assertTrue(all(m['error'] for m in missing[0]['metrics']))
        with patch.object(judge_runner, 'evaluate', return_value=one) as called:
            judge_runner.judge_stage(cases, 'generation', meta, skip={'NASA-F-001:generation'})
        self.assertEqual([tc.name for tc in called.call_args.kwargs['test_cases']], ['NASA-F-002:generation'])

    def test_retrieval_stage_uses_contextual_metrics_only(self):
        self.assertEqual(deepeval_suite.stage_metric_names('retrieval_pre_rerank'), config.RETRIEVAL_METRICS)


class ContextCaptureTests(unittest.TestCase):
    def test_answer_one_maps_recorded_ranks_to_texts(self):
        ids = [d.metadata['chunk_id'] for d in DOCUMENTS]
        result = answered(None, DOCUMENTS[1], 'x')
        result['retrieval'] = {'chunk_ids': ids[1:3], 'dense_ranks': {ids[2]: 1, ids[1]: 2}, 'sparse_ranks': {ids[1]: 1},
                               'fusion': [{'chunk_id': ids[1], 'rank': 1, 'rrf_score': .03}, {'chunk_id': ids[2], 'rank': 2, 'rrf_score': .02}],
                               'reranker': {'scores': [{'chunk_id': ids[1], 'rank': 1, 'score': 3.0}, {'chunk_id': ids[2], 'rank': 2, 'score': 1.0}]}}
        token = adapter._BASELINE.set(None)
        with patch('backend.core.rag_engine.ask_question', return_value=result), \
                patch('backend.core.rag_engine.load_rag_chain', return_value=object()), \
                patch.object(adapter, '_start_question_budget', return_value=token):
            case = adapter.answer_one(BY_ID['NASA-F-001'], job_id=build_chunks.JOB_ID, scope='public',
                                      documents=DOCUMENTS, budget_original=None)
        ctx = case['contexts']
        self.assertEqual(ctx['dense_ranking'], [ids[2], ids[1]])
        self.assertEqual(ctx['fused_ranking'], ids[1:3])
        self.assertEqual(ctx['reranked_ranking'], ids[1:3])
        self.assertEqual([c['text'] for c in ctx['final']], [DOCUMENTS[1].page_content, DOCUMENTS[2].page_content])
        self.assertIsNone(case['error'])

    def test_answer_one_records_errors_instead_of_inventing_results(self):
        token = adapter._BASELINE.set(None)
        with patch('backend.core.rag_engine.ask_question', side_effect=RuntimeError('No eligible generation route')), \
                patch('backend.core.rag_engine.load_rag_chain', return_value=object()), \
                patch.object(adapter, '_start_question_budget', return_value=token):
            case = adapter.answer_one(BY_ID['NASA-F-001'], job_id=build_chunks.JOB_ID, scope='public',
                                      documents=DOCUMENTS, budget_original=None)
        self.assertIsNone(case['result'])
        self.assertEqual(case['error']['type'], 'RuntimeError')
        self.assertEqual(case['contexts']['final'], [])

    def test_per_minute_cap_waits_then_retries_and_stops_when_still_capped(self):
        capped = {**captured_case(), 'result': None, 'calls': [],
                  'error': {'type': 'RuntimeError', 'message': 'No eligible generation route'}}
        tmp = Path(tempfile.mkdtemp())
        sleeps = []
        common = dict(scope='owner', out_dir=tmp / 'a', cache_path=tmp / 'c.json', progress=lambda _: None,
                      rate_waits=2, rate_wait_seconds=65, sleep=sleeps.append)
        with patch.object(adapter, 'verify_index', return_value=DOCUMENTS), patch.object(adapter, 'warm_up', return_value=0), \
                patch('backend.core.vector_store.get_embeddings'), patch('backend.db.get_job', return_value={'embedding_route': 'x'}), \
                patch.object(adapter.QueryEmbeddingCache, 'prefetch', return_value=0), \
                patch('backend.core.llm_gateway.operation_scope'), patch.object(adapter, 'per_question_job_budget'):
            with patch.object(adapter, 'answer_one', side_effect=[capped, captured_case()]):
                run = adapter.answer_all([BY_ID['NASA-F-001']], **common)
            self.assertIsNone(run['stopped_early'])
            self.assertEqual(sleeps, [65])
            with patch.object(adapter, 'answer_one', return_value=capped):
                run = adapter.answer_all([BY_ID['NASA-F-002']], **common)
            self.assertEqual(run['stopped_early']['waits'], 2)
            self.assertFalse((tmp / 'a' / 'NASA-F-002.json').exists())
            rejected = {**capped, 'calls': [{'alias': 'groq-economy', 'ok': True, 'raw_output': '{}'}]}
            with patch.object(adapter, 'answer_one', return_value=rejected):
                run = adapter.answer_all([BY_ID['NASA-F-003']], **common)
            self.assertIsNone(run['stopped_early'])
            saved = json.loads((tmp / 'a' / 'NASA-F-003.json').read_text())
            self.assertEqual(saved['error']['kind'], 'all_route_outputs_rejected')

    def test_stage_timer_parses_app_telemetry(self):
        from backend.core.telemetry import duration
        with adapter.capture_stages() as timer, duration('rerank'):
            pass
        self.assertEqual(timer.stages[0]['stage'], 'rerank')
        self.assertEqual(timer.stages[0]['status'], 'success')


class CitationTests(unittest.TestCase):
    doc = DOCUMENTS[0]
    final = {doc.metadata['chunk_id']: chunk(doc)}

    def test_valid_citation(self):
        result = answered(None, self.doc, 'NASA has 23 satellites looking down')
        self.assertTrue(deterministic.check_citations(result, self.final)['all_valid'])

    def test_fabricated_quote_fails(self):
        result = answered(None, self.doc, 'NASA has 99 satellites')
        self.assertFalse(deterministic.check_citations(result, self.final)['details'][0]['exact_quote'])

    def test_citation_outside_retrieved_context_fails(self):
        result = answered(None, DOCUMENTS[5], DOCUMENTS[5].page_content[:30])
        self.assertFalse(deterministic.check_citations(result, self.final)['details'][0]['in_retrieved_context'])

    def test_wrong_timestamps_fail(self):
        result = answered(None, self.doc, 'NASA has 23 satellites looking down')
        result['citations'][0]['start_ms'] += 1
        self.assertFalse(deterministic.check_citations(result, self.final)['details'][0]['timestamps_match_chunk'])

    def test_structure_rejects_unexpected_fields_and_uncited_answers(self):
        result = answered(None, self.doc, 'quote')
        self.assertEqual(deterministic.check_structure(result), [])
        self.assertTrue(deterministic.check_structure({**result, 'extra': 1}))
        self.assertTrue(deterministic.check_structure({**result, 'citations': []}))
        self.assertEqual(deterministic.check_structure(abstained()), [])

    def test_adversarial_model_outputs_are_handled(self):
        results = deterministic.adversarial_structure_suite(DOCUMENTS)
        self.assertGreaterEqual(len(results), 14)
        self.assertEqual([r['name'] for r in results if not r['passed']], [])


class AbstentionTests(unittest.TestCase):
    def test_behavior_expectations(self):
        doc = DOCUMENTS[0]
        self.assertTrue(deterministic.check_behavior(answered(None, doc, 'q'), BY_ID['NASA-F-001'])['correct'])
        self.assertFalse(deterministic.check_behavior(abstained(), BY_ID['NASA-F-001'])['correct'])
        self.assertTrue(deterministic.check_behavior(abstained(), BY_ID['NASA-U-001'])['correct'])
        self.assertFalse(deterministic.check_behavior(answered(None, doc, 'q'), BY_ID['NASA-U-001'])['correct'])
        self.assertTrue(deterministic.check_behavior(abstained(), BY_ID['NASA-A-001'])['correct'])

    def test_false_premise_must_be_corrected(self):
        golden = BY_ID['NASA-P-001']
        doc = next(d for d in DOCUMENTS if d.metadata['chunk_id'] in golden['gold_chunk_ids'])
        corrected = answered(None, doc, 'q', answer='No: methane lasts only around a decade, shorter than CO2.')
        accepted = answered(None, doc, 'q', answer='Methane stays longer because it is heavier.')
        self.assertTrue(deterministic.check_behavior(corrected, golden)['correct'])
        self.assertFalse(deterministic.check_behavior(accepted, golden)['correct'])

    def test_abstention_metrics(self):
        rows = [{'expected': 'abstain', 'outcome': 'abstained'}, {'expected': 'abstain', 'outcome': 'answered'},
                {'expected': 'answer', 'outcome': 'abstained'}, {'expected': 'answer', 'outcome': 'answered'}]
        m = deterministic.abstention_metrics(rows)
        self.assertEqual((m['abstention_precision'], m['abstention_recall'], m['false_abstention_rate']), (0.5, 0.5, 0.5))


class IRAndRegistryTests(unittest.TestCase):
    def test_ir_metrics(self):
        ranked, gold = ['a', 'b', 'c', 'd'], ['b', 'z']
        self.assertEqual(ir.recall_at_k(ranked, gold, 4), 0.5)
        self.assertEqual(ir.mrr(ranked, gold), 0.5)
        self.assertEqual(ir.hit_at_k(ranked, gold, 1), 0.0)
        self.assertAlmostEqual(ir.ndcg_at_k(['b'], ['b'], 4), 1.0)
        self.assertIsNone(ir.score_ranking(ranked, [], 4))

    def test_registry_uses_tolerance_and_direction(self):
        self.assertEqual(registry.compare('deepeval.generation.Faithfulness.avg_score', .80, .83), 'flat')
        self.assertEqual(registry.compare('deepeval.generation.Faithfulness.avg_score', .80, .70), 'regressed')
        self.assertEqual(registry.compare('latency.end_to_end.p95_ms', 1000, 700), 'improved')

    def test_bootstrap_is_deterministic(self):
        a, b = [0, 0, 1, 1], [1, 1, 1, 1]
        self.assertEqual(experiments.paired_bootstrap(a, b), experiments.paired_bootstrap(a, b))


class CredentialAndBudgetTests(unittest.TestCase):
    def setUp(self):
        self.ledger_path = Path(tempfile.mkdtemp()) / 'ledger.json'

    def test_authorisation_requires_flag_budget_and_key(self):
        base = {'EVAL_ALLOW_PAID_JUDGE': '1', 'EVAL_JUDGE_BUDGET_USD': '2', 'META_API_KEY': FAKE_KEY}
        self.assertEqual(judge.require_judge_authorisation(base), 2.0)
        for missing in base:
            with self.subTest(missing=missing), self.assertRaises(judge.JudgeConfigError) as raised:
                judge.require_judge_authorisation({k: v for k, v in base.items() if k != missing})
            self.assertNotIn(FAKE_KEY, str(raised.exception))
        with self.assertRaises(judge.JudgeConfigError):
            judge.require_judge_authorisation({**base, 'EVAL_JUDGE_BUDGET_USD': '0'})

    def test_missing_key_refuses_to_build_client(self):
        with patch.dict(os.environ, {'META_API_KEY': ''}), self.assertRaises(judge.JudgeConfigError):
            judge.MetaJudge(judge.SpendLedger(1, path=self.ledger_path))

    def test_contributor_tier_is_refused(self):
        with self.assertRaises(judge.JudgeConfigError):
            judge.MetaJudge(judge.SpendLedger(1, path=self.ledger_path), client=fake_client(), model='muse-spark-1.3-contributor')

    def test_schema_output_is_validated_and_cost_recorded(self):
        meta = judge.MetaJudge(judge.SpendLedger(1, path=self.ledger_path), client=fake_client())
        result = meta.probe()
        self.assertEqual(result['verdict'], 'ok')
        expected = (100 * config.JUDGE_PRICE_INPUT + 50 * config.JUDGE_PRICE_OUTPUT) / 1e6
        self.assertAlmostEqual(meta.ledger.spent, expected)
        sent = meta.model.chat.completions.calls[0]
        self.assertEqual(sent['model'], 'muse-spark-1.3')
        self.assertEqual(sent['response_format']['type'], 'json_schema')
        ledger = json.loads(self.ledger_path.read_text())
        self.assertEqual(ledger['calls'], 1)

    def test_call_that_could_exceed_budget_is_never_sent(self):
        meta = judge.MetaJudge(judge.SpendLedger(0.000001, path=self.ledger_path), client=fake_client())
        with self.assertRaises(judge.BudgetExceeded):
            meta.generate('prompt')
        self.assertEqual(meta.model.chat.completions.calls, [])

    def test_provider_errors_never_echo_the_key(self):
        error = RuntimeError(f'bad auth for key {FAKE_KEY}')
        meta = judge.MetaJudge(judge.SpendLedger(1, path=self.ledger_path), client=fake_client(error=error))
        with self.assertRaises(judge.JudgeCallError) as raised:
            meta.generate('prompt')
        self.assertNotIn(FAKE_KEY, str(raised.exception))
        self.assertNotIn(FAKE_KEY, self.ledger_path.read_text())

    def test_json_schema_rejection_falls_back_to_prompt_json(self):
        class BadRequest(Exception):
            status_code = 400
        completions = FakeCompletions()
        original = completions.create
        completions.create = lambda **o: (_ for _ in ()).throw(BadRequest()) if 'response_format' in o else original(**o)
        meta = judge.MetaJudge(judge.SpendLedger(1, path=self.ledger_path), client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
        self.assertEqual(meta.probe()['json_schema_supported'], False)

    def test_redact(self):
        with patch.dict(os.environ, {'META_API_KEY': FAKE_KEY}):
            self.assertEqual(guards.redact(f'x {FAKE_KEY} y'), 'x <META_API_KEY> y')


class GuardTests(unittest.TestCase):
    def test_offline_guard_refuses_external_network(self):
        with guards.network_guard(guards.allowed_hosts('offline')):
            with self.assertRaises(guards.NetworkBlocked):
                socket.create_connection(('api.meta.ai', 443), timeout=1)
            with socket.socket() as raw, self.assertRaises(guards.NetworkBlocked):
                raw.connect(('93.184.216.34', 80))

    def test_local_guard_without_judge_refuses_meta_and_telemetry_hosts(self):
        with guards.network_guard(guards.allowed_hosts('local')):
            for host in ('api.meta.ai', 'api.confident-ai.com', 'us.i.posthog.com'):
                with self.subTest(host=host), self.assertRaises(guards.NetworkBlocked):
                    socket.getaddrinfo(host, 443)

    def test_eval_database_must_be_disposable_loopback(self):
        ok = 'postgresql://postgres:pw@127.0.0.1:55491/ava_eval'
        self.assertEqual(guards.require_eval_database(ok), ok)
        for bad in ('postgresql://u:p@db.neon.tech:5432/ava_eval', 'postgresql://u:p@127.0.0.1:55432/ava_eval',
                    'postgresql://u:p@127.0.0.1:55491/postgres'):
            with self.subTest(bad=bad), self.assertRaises(guards.UnsafeDatabase):
                guards.require_eval_database(bad)

    def test_environment_forces_paid_routes_off_and_drops_dev_database(self):
        with tempfile.NamedTemporaryFile('w', suffix='.env', delete=False) as handle:
            handle.write('ENABLE_PAID_META=true\nENABLE_PUBLIC_PAID_FALLBACK=true\nDATABASE_URL=postgresql://x@neon.tech/prod\n')
        env = guards.apply_environment('local', env={}, dotenv_path=handle.name)
        os.unlink(handle.name)
        self.assertEqual((env['ENABLE_PAID_META'], env['ENABLE_PUBLIC_PAID_FALLBACK']), ('false', 'false'))
        self.assertNotIn('DATABASE_URL', env)
        offline = guards.apply_environment('offline', env={'ENABLE_PROVIDER_CALLS': 'true'})
        self.assertEqual(offline['ENABLE_PROVIDER_CALLS'], 'false')


class ReportTests(unittest.TestCase):
    def test_reports_from_fixture_run(self):
        raw = Path(tempfile.mkdtemp())
        out = Path(tempfile.mkdtemp())
        (raw / 'answers').mkdir()
        cases = [captured_case(), captured_case('NASA-U-001', abstained())]
        for case in cases:
            (raw / 'answers' / f'{case["golden"]["id"]}.json').write_text(json.dumps(case))
        (raw / 'judge').mkdir()
        (raw / 'judge' / 'generation.json').write_text(json.dumps([{'name': 'NASA-F-001:generation', 'success': True, 'metrics': [
            {'name': 'Faithfulness', 'score': 0.9, 'success': True, 'threshold': 0.8, 'reason': 'ok', 'error': None, 'evaluation_model': 'm'},
            {'name': 'Answer Relevancy', 'score': None, 'success': False, 'threshold': 0.7, 'reason': None,
             'error': 'BudgetExceeded', 'evaluation_model': 'm'}]}]))
        with patch.object(config, 'LEDGER_FILE', raw / 'none.json'):
            metrics = report.write_reports('local', raw_dir=raw, out_dir=out, adversarial=[], dataset_size=2)
        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(report.REPORT_FILES))
        faith = metrics['deepeval']['generation']['Faithfulness']
        self.assertEqual((faith['avg_score'], faith['passed']), (0.9, 1))
        self.assertEqual(metrics['deepeval']['generation']['Answer Relevancy']['errors'], 1)
        self.assertIsNone(metrics['deepeval']['generation']['Answer Relevancy']['avg_score'])
        self.assertEqual(metrics['deterministic']['behavior_accuracy'], 1.0)
        self.assertEqual(metrics['deterministic']['citation_validity'], 1.0)
        self.assertIn('BudgetExceeded', (out / 'failure_analysis.md').read_text())
        self.assertIn('metric_id,value', (out / 'metrics.csv').read_text())

    def test_empty_run_reports_not_run_instead_of_scores(self):
        raw, out = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        with patch.object(config, 'LEDGER_FILE', raw / 'none.json'):
            report.write_reports('offline', raw_dir=raw, out_dir=out, adversarial=[], dataset_size=45)
        self.assertIn('Not run.', (out / 'evaluation_summary.md').read_text())
        self.assertIn('Answer stage not run', (out / 'failure_analysis.md').read_text())

    def test_percentile_interpolates(self):
        self.assertEqual(report.percentile([0, 10], .5), 5)


if __name__ == '__main__':
    unittest.main()
