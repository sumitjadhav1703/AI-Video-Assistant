"""Export the committed evaluation artefacts into one compact JSON file for the web /eval and /usage pages.

Run from the repository root with the evaluation venv:
  evaluation/.venv/bin/python scripts/export_eval_summary.py
Writes web/src/data/evaluation.json. Only summary numbers and short excerpts are exported, no raw provider payloads.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.metrics import ir  # noqa: E402
from evaluation.runners.experiments import paired_bootstrap  # noqa: E402

REPORTS = ROOT / 'evaluation' / 'reports'
FUTURE = ROOT / 'future-improvements' / 'v2-rag-pipeline' / 'reports'
USAGE = ROOT / 'docs' / 'usage_measurement.json'
OUT = ROOT / 'web' / 'src' / 'data' / 'evaluation.json'
V1_JUDGE_RUNS = 5  # the first five ledger entries are the v1 probe, pilot, full run and two resumes
VARIANTS = {'dense_only': 'Dense only (pgvector)', 'bm25_only': 'BM25 only', 'hybrid_rrf': 'Hybrid RRF, no rerank',
            'hybrid_rerank': 'Hybrid + TinyBERT rerank (production)'}


def load(path):
    return json.loads(path.read_text())


def clip(text, limit=420):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def round_tree(value, digits=4):
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {k: round_tree(v, digits) for k, v in value.items()}
    if isinstance(value, list):
        return [round_tree(v, digits) for v in value]
    return value


def retrieval(analysis):
    cases = [c for c in analysis['production_capture']['cases'] if c['gold_chunk_ids'] and c['rankings'].get('hybrid_rerank')]
    per = {name: [ir.score_ranking(c['rankings'][name] or [], c['gold_chunk_ids'], 4) for c in cases] for name in VARIANTS}
    rows = []
    base = [p['recall'] for p in per['hybrid_rerank']]
    for name, label in VARIANTS.items():
        means = ir.mean_scores(per[name])
        ci = None if name == 'hybrid_rerank' else paired_bootstrap(base, [p['recall'] for p in per[name]])
        rows.append({'variant': name, 'label': label, 'recall': means['recall'], 'mrr': means['mrr'], 'ndcg': means['ndcg'],
                     'precision': means['precision'], 'vs_production_recall': ci})
    return {'n': len(cases), 'k': 4, 'variants': rows,
            'candidate_recall': analysis['production_capture']['candidate_recall'],
            'offline': analysis.get('offline', {}).get('ir') if analysis.get('offline') else None}


def cases(rows):
    out = []
    for r in rows:
        judge = {}
        for stage, metrics in (r.get('deepeval') or {}).items():
            judge[stage] = [{'metric': m['name'], 'score': m['score'], 'passed': m['success'], 'threshold': m['threshold'],
                             'reason': clip(m['reason'], 260), 'error': m['error']} for m in metrics]
        out.append({'id': r['id'], 'category': r['category'], 'question': r['question'],
                    'expected_behavior': r['expected_behavior'], 'expected_answer': clip(r['expected_answer'], 360),
                    'answer': clip(r.get('answer'), 480) if r.get('answer') else None, 'abstained': r.get('abstained'),
                    'citations': [{'text': clip(c['text'], 220), 'start_ms': c['start_ms'], 'end_ms': c['end_ms']}
                                  for c in (r.get('citations') or [])],
                    'behavior': r.get('behavior'), 'error': (r.get('error') or {}).get('type'),
                    'model': (r.get('models_used') or [None])[-1], 'judge': judge})
    return out


def costs():
    ledger_path = REPORTS / 'judge_ledger.json'
    if not ledger_path.exists():
        return None
    runs = sorted(load(ledger_path)['runs'].items())[:V1_JUDGE_RUNS]
    labels = ['Probe (1 call)', 'Pilot (3 cases)', 'Full run, first attempt', 'Resume 1 (missing cases)', 'Resume 2 (errored rows)']
    rows = [{'label': label, 'usd': r['usd'], 'calls': r['calls'], 'input_tokens': r['input_tokens'],
             'output_tokens': r['output_tokens']} for label, (_, r) in zip(labels, runs)]
    return {'model': 'meta/muse-spark-1.3', 'runs': rows, 'total_usd': sum(r['usd'] for r in rows),
            'total_calls': sum(r['calls'] for r in rows),
            'total_input_tokens': sum(r['input_tokens'] for r in rows),
            'total_output_tokens': sum(r['output_tokens'] for r in rows)}


def main():
    metrics = load(REPORTS / 'metrics.json')
    latency = metrics['latency']
    det = metrics['deterministic']
    summary = {
        'generated_from': 'evaluation/reports (v1 run, 13 Nov 2026)',
        'source': {'title': 'What NASA Knows from Decades of Earth System Observations', 'speaker': 'Karen St. Germain',
                   'url': 'https://svs.gsfc.nasa.gov/31168/', 'licence': 'US government work (public domain)',
                   'duration': '13 min 35 s', 'chunks': 22, 'goldens': 45},
        'judge': 'meta/muse-spark-1.3', 'deepeval_version': metrics['meta']['deepeval_version'],
        'generators': metrics['meta']['generator_models_observed'],
        'thresholds': metrics['meta']['thresholds'],
        'deepeval': metrics['deepeval'],
        'deterministic': {k: det[k] for k in ('cases_with_result', 'cases_with_error', 'structure_validity', 'citations_total',
                                              'citation_validity', 'answered_with_gold_citation_rate', 'behavior_accuracy',
                                              'behavior_by_category', 'abstention', 'adversarial_cases', 'adversarial_pass_rate')},
        'retrieval': retrieval(load(REPORTS / 'retrieval_analysis.json')),
        'latency': {'warm': latency['warm'], 'provider_calls': latency['provider_calls'], 'candidates': latency['candidates'],
                    'note': latency['note']},
        'cost': costs(),
        'cases': cases(load(REPORTS / 'test_case_results.json')),
        'future': None,
        'usage': load(USAGE) if USAGE.exists() else None,
    }
    comparison = FUTURE / 'comparison_v1-pinned_vs_v2-iter1.json'
    if comparison.exists():
        c = load(comparison)
        summary['future'] = {'cases_compared': c['cases_compared'], 'deterministic': c['deterministic'],
                             'deepeval': c['deepeval'], 'latency': c['latency'], 'gate': c['gate'],
                             'path': 'future-improvements/v2-rag-pipeline/'}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(round_tree(summary), separators=(',', ':'), ensure_ascii=False))
    print(f'wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB, {len(summary["cases"])} cases)')


if __name__ == '__main__':
    main()
