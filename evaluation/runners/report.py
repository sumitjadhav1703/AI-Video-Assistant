"""Turn raw run artefacts into the eight report files. Missing stages are reported as 'not run', never filled in."""
import csv
import json
import statistics
from collections import Counter
from datetime import datetime, timezone

from evaluation import config
from evaluation.metrics import deterministic, ir
from evaluation.runners import experiments

REPORT_FILES = ('evaluation_summary.md', 'metrics.json', 'metrics.csv', 'test_case_results.json',
                'retrieval_analysis.json', 'latency_results.json', 'failure_analysis.md', 'experiment_comparison.md')


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    low, high = int(pos), min(int(pos) + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (pos - low)


def distribution(values):
    values = [v for v in values if v is not None]
    if not values:
        return {'n': 0}
    return {'n': len(values), 'p50': percentile(values, .5), 'p95': percentile(values, .95),
            'p99': percentile(values, .99), 'mean': statistics.fmean(values), 'max': max(values)}


def _load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def load_artifacts(raw_dir=config.RAW_DIR):
    from evaluation.runners.adapter import load_answers
    return {'answers': load_answers(raw_dir / 'answers'),
            'judge': {p.stem: json.loads(p.read_text()) for p in sorted((raw_dir / 'judge').glob('*.json'))}
            if (raw_dir / 'judge').exists() else {},
            'offline': _load(raw_dir / 'offline.json'),
            'runs': [json.loads(line) for line in (raw_dir / 'run_log.jsonl').read_text().splitlines()]
            if (raw_dir / 'run_log.jsonl').exists() else [],
            'ledger': _load(config.LEDGER_FILE)}


def summarize_judge(rows):
    """{metric: {n, avg, min, max, passed, failed, errors, pass_rate, threshold}} kept per metric, never pooled."""
    buckets = {}
    for row in rows:
        for m in row['metrics']:
            b = buckets.setdefault(m['name'], {'scores': [], 'passed': 0, 'failed': 0, 'errors': 0, 'threshold': m['threshold']})
            if m['error'] or m['score'] is None:
                b['errors'] += 1
                continue
            b['scores'].append(m['score'])
            b['passed' if m['success'] else 'failed'] += 1
    out = {}
    for name, b in buckets.items():
        s = b['scores']
        out[name] = {'n_scored': len(s), 'avg_score': statistics.fmean(s) if s else None, 'min_score': min(s) if s else None,
                     'max_score': max(s) if s else None, 'passed': b['passed'], 'failed': b['failed'], 'errors': b['errors'],
                     'pass_rate': b['passed'] / len(s) if s else None, 'threshold': b['threshold']}
    return out


def case_rows(answers, judge):
    by_case = {}
    for stage, rows in judge.items():
        if stage == 'sanity':
            continue
        for row in rows:
            case_id = row['name'].split(':')[0]
            by_case.setdefault(case_id, {})[stage] = row['metrics']
    rows = []
    for case_id, case in sorted(answers.items()):
        golden, result = case['golden'], case['result']
        entry = {'id': case_id, 'category': golden['category'], 'question': golden['question'],
                 'expected_behavior': golden['expected_behavior'], 'expected_answer': golden['expected_answer'],
                 'error': case['error'], 'scope': case.get('scope'),
                 'models_used': [f"{c['provider']}:{c['model']}" for c in case['calls'] if c.get('ok')],
                 'generation_attempts': len(case['calls']), 'deepeval': by_case.get(case_id, {})}
        if result is not None:
            final = {c['chunk_id']: c for c in case['contexts']['final']}
            entry.update(answer=result['answer'], abstained=result['abstained'], citations=result['citations'],
                         structure_errors=deterministic.check_structure(result),
                         citation_check=deterministic.check_citations(result, final),
                         evidence_alignment=deterministic.evidence_alignment(result, golden),
                         behavior=deterministic.check_behavior(result, golden))
        elif case['error']:
            # The user would receive an error (HTTP 503) instead of an answer or abstention.
            entry['behavior'] = {'expected': golden['expected_behavior'], 'outcome': 'error', 'correct': False,
                                 'reason': f'request failed: {case["error"].get("kind") or case["error"]["type"]}'}
        rows.append(entry)
    return rows


def deterministic_summary(rows, adversarial):
    judged = [r for r in rows if 'behavior' in r]           # includes request errors (scored incorrect)
    done = [r for r in judged if 'citation_check' in r]      # cases with an app result
    citations = [c for r in done for c in r['citation_check']['details']]
    answered = [r for r in done if not r['abstained']]
    gold_hits = [r['evidence_alignment']['gold_hit'] for r in answered if r['evidence_alignment']['gold_hit'] is not None]
    by_category = {}
    for r in judged:
        b = by_category.setdefault(r['category'], {'n': 0, 'correct': 0})
        b['n'] += 1
        b['correct'] += r['behavior']['correct']
    return {
        'cases_with_result': len(done), 'cases_with_error': sum(1 for r in rows if r['error']),
        'structure_validity': sum(not r['structure_errors'] for r in done) / len(done) if done else None,
        'citations_total': len(citations),
        'citation_validity': sum(c['valid'] for c in citations) / len(citations) if citations else None,
        'citation_in_context_rate': sum(c['in_retrieved_context'] for c in citations) / len(citations) if citations else None,
        'citation_exact_quote_rate': sum(c['exact_quote'] for c in citations) / len(citations) if citations else None,
        'citation_timestamp_match_rate': sum(c['timestamps_match_chunk'] for c in citations) / len(citations) if citations else None,
        'answered_with_gold_citation_rate': sum(gold_hits) / len(gold_hits) if gold_hits else None,
        'behavior_accuracy': sum(r['behavior']['correct'] for r in judged) / len(judged) if judged else None,
        'behavior_by_category': {k: {**v, 'accuracy': v['correct'] / v['n']} for k, v in sorted(by_category.items())},
        'abstention': deterministic.abstention_metrics([r['behavior'] for r in judged]),
        'adversarial_cases': len(adversarial or []),
        'adversarial_pass_rate': sum(a['passed'] for a in adversarial) / len(adversarial) if adversarial else None,
    }


def latency_summary(answers):
    cases = list(answers.values())
    warm = [c for c in cases if not c.get('cold')]
    stage = lambda cs, name: [s['elapsed_ms'] for c in cs for s in c['stages'] if s['stage'] == name and s['status'] == 'success']
    calls = [call for c in cases for call in c['calls']]
    out = {'note': 'Query embeddings were fetched in one batched request and served from cache, so dense_retrieval '
                   'measures the pgvector search only. Cold = first measured question of a run (excluded from warm stats).',
           'cases': len(cases), 'cold_cases': len(cases) - len(warm)}
    for label, subset in (('warm', warm), ('all', cases)):
        out[label] = {name: distribution(stage(subset, name)) for name in ('dense_retrieval', 'sparse_retrieval', 'rrf', 'rerank')}
        out[label]['generation'] = distribution([c['elapsed_ms'] for case in subset for c in case['calls'] if c.get('ok')])
        out[label]['end_to_end'] = distribution([c['e2e_ms'] for c in subset if c['result'] is not None])
    retrieval = [c['result']['retrieval'] for c in cases if c['result']]
    out['candidates'] = {k: distribution([r.get(k) for r in retrieval]) for k in ('dense_count', 'sparse_count', 'fused_count', 'final_count')}
    out['provider_calls'] = {'total_attempts': len(calls), 'failed_attempts': sum(not c.get('ok') for c in calls),
                             'questions_with_retry': sum(len(c['calls']) > 1 for c in cases),
                             'per_question': distribution([len(c['calls']) for c in cases]),
                             'failures_by_type': dict(Counter(c['error'] for c in calls if not c.get('ok'))),
                             # ok = the provider replied; the app may still reject the output (schema/grounding) and fail over.
                             'provider_responses_by_model': dict(Counter(f"{c['provider']}:{c['model']}" for c in calls if c.get('ok'))),
                             'outputs_rejected_by_app': sum(sum(1 for x in c['calls'] if x.get('ok')) - (1 if c['result'] and c['calls'] else 0)
                                                            for c in cases),
                             'final_answers_by_model': dict(Counter(c['result']['model'].get('model', 'none (no generation)')
                                                                    for c in cases if c['result']))}
    out['request_errors'] = dict(Counter(c['error']['type'] for c in cases if c['error']))
    return out


def retrieval_analysis(answers):
    rows = []
    for case_id, case in sorted(answers.items()):
        gold = case['golden']['gold_chunk_ids']
        ctx = case['contexts']
        rank_of = lambda ranking: {g: (ranking.index(g) + 1 if g in ranking else None) for g in gold}
        rows.append({'id': case_id, 'category': case['golden']['category'], 'gold_chunk_ids': gold,
                     'gold_rank': {name: rank_of(ctx.get(field) or []) for name, field in experiments.VARIANTS.items()},
                     'rankings': {name: ctx.get(field) for name, field in experiments.VARIANTS.items()},
                     'reranker_truncated': (ctx.get('reranker') or {}).get('truncated_count')})
    means, _ = experiments.ir_table(list(answers.values()))
    return {'k': config.FINAL_K, 'ir_at_k': means, 'candidate_recall': experiments.candidate_recall(list(answers.values())),
            'cases': rows}


def _fmt(value, digits=3):
    return '—' if value is None else (f'{value:.{digits}f}' if isinstance(value, float) else str(value))


def write_reports(mode, *, raw_dir=config.RAW_DIR, out_dir=config.REPORTS_DIR, adversarial=None, dataset_size=None):
    art = load_artifacts(raw_dir)
    answers, judge = art['answers'], art['judge']
    rows = case_rows(answers, judge)
    det = deterministic_summary(rows, adversarial)
    deepeval_scores = {stage: summarize_judge(r) for stage, r in judge.items()}
    latency = latency_summary(answers) if answers else None
    retrieval = retrieval_analysis(answers) if answers else None
    exp_means, exp_cases = experiments.ir_table(list(answers.values())) if answers else ({}, {})
    comparisons = experiments.compare_to_baseline(exp_cases) if answers else {}
    offline = art['offline']
    generators = sorted({m for r in rows for m in r['models_used']})
    ledger_runs = (art['ledger'] or {}).get('runs', {})
    meta = {'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'mode': mode,
            'mode_description': 'local execution, remote inference' if mode == 'local' else 'fully offline (no external inference)',
            'deepeval_version': config.DEEPEVAL_VERSION, 'dataset_size': dataset_size,
            'source_id': 'nasa-cop26-stgermain', 'judge_model': f'meta/{config.JUDGE_MODEL}' if judge else None,
            'generator_models_observed': generators, 'answers_captured': len(answers),
            'stages_run': {'answer': bool(answers), 'judge': sorted(judge), 'offline': offline is not None},
            'judge_spend_usd': round(sum(r['usd'] for r in ledger_runs.values()), 6) if ledger_runs else 0.0,
            'thresholds': config.THRESHOLDS, 'runs': art['runs']}
    metrics = {'meta': meta, 'deepeval': deepeval_scores, 'deterministic': det,
               'ir': {'production_capture': exp_means, 'offline': offline and offline.get('ir')},
               'latency': latency}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'metrics.json').write_text(json.dumps(metrics, indent=2, default=str))
    (out_dir / 'test_case_results.json').write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str))
    (out_dir / 'retrieval_analysis.json').write_text(json.dumps(
        {'production_capture': retrieval, 'offline': offline}, indent=1, default=str))
    (out_dir / 'latency_results.json').write_text(json.dumps(
        {'production_capture': latency, 'offline': offline and offline.get('latency')}, indent=2, default=str))
    _write_csv(out_dir / 'metrics.csv', metrics)
    (out_dir / 'experiment_comparison.md').write_text(_experiments_md(exp_means, comparisons, retrieval, offline))
    (out_dir / 'failure_analysis.md').write_text(_failures_md(rows, judge, adversarial))
    (out_dir / 'evaluation_summary.md').write_text(_summary_md(meta, deepeval_scores, det, latency, exp_means, offline))
    return metrics


def _flatten(prefix, value, out):
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f'{prefix}.{k}' if prefix else str(k), v, out)
    elif isinstance(value, (int, float)) and not isinstance(value, bool) or value is None:
        out.append((prefix, value))


def _write_csv(path, metrics):
    rows = []
    for section in ('deepeval', 'deterministic', 'ir', 'latency'):
        _flatten(section, metrics[section], rows)
    with path.open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['metric_id', 'value'])
        writer.writerows(rows)


def _summary_md(meta, deepeval_scores, det, latency, exp_means, offline):
    lines = [f'# Evaluation summary', '',
             f'- Generated: {meta["generated_at"]}', f'- Mode: **{meta["mode"]}** ({meta["mode_description"]})',
             f'- DeepEval: {meta["deepeval_version"]}', f'- Dataset: {meta["dataset_size"]} goldens from `{meta["source_id"]}` '
             '(public-domain NASA talk)', f'- Answers captured: {meta["answers_captured"]}',
             f'- Generator models observed: {", ".join(meta["generator_models_observed"]) or "none (answer stage not run)"}',
             f'- Judge: {meta["judge_model"] or "not run"}; judge spend recorded: ${meta["judge_spend_usd"]:.4f}', '']
    lines += ['## DeepEval (LLM-as-a-judge)', '']
    if not deepeval_scores:
        lines += ['Not run. No DeepEval scores exist for this report; none are estimated.', '']
    for stage, scores in deepeval_scores.items():
        lines += [f'### {stage}', '', '| Metric | Threshold | Avg | Min | Max | Passed | Failed | Errors |', '|---|---|---|---|---|---|---|---|']
        lines += [f'| {name} | {s["threshold"]} | {_fmt(s["avg_score"])} | {_fmt(s["min_score"])} | {_fmt(s["max_score"])} | '
                  f'{s["passed"]} | {s["failed"]} | {s["errors"]} |' for name, s in scores.items()]
        lines.append('')
    lines += ['## Application checks (deterministic, separate from DeepEval)', '']
    for key in ('cases_with_result', 'cases_with_error', 'structure_validity', 'citations_total', 'citation_validity',
                'citation_exact_quote_rate', 'citation_timestamp_match_rate', 'answered_with_gold_citation_rate',
                'behavior_accuracy', 'adversarial_cases', 'adversarial_pass_rate'):
        lines.append(f'- {key}: {_fmt(det[key])}')
    lines += [f'- abstention: ' + ', '.join(f'{k}={_fmt(v)}' for k, v in det['abstention'].items()), '']
    lines += ['## Retrieval (gold chunk ids, k=4)', '']
    if exp_means:
        lines += ['| Variant | n | hit | recall | precision | MRR | nDCG |', '|---|---|---|---|---|---|---|']
        lines += [f'| {n} | {m["n"]} | {_fmt(m.get("hit"))} | {_fmt(m.get("recall"))} | {_fmt(m.get("precision"))} | '
                  f'{_fmt(m.get("mrr"))} | {_fmt(m.get("ndcg"))} |' for n, m in exp_means.items()]
    else:
        lines.append('Production capture not run.')
    if offline:
        lines += ['', 'Offline (local BM25 and TinyBERT only):', '']
        lines += [f'- {n}: recall={_fmt(m.get("recall"))}, MRR={_fmt(m.get("mrr"))}, nDCG={_fmt(m.get("ndcg"))} (n={m["n"]})'
                  for n, m in offline['ir'].items()]
    lines += ['', '## Latency', '']
    if latency:
        warm = latency['warm']
        lines += [f'- {name}: p50={_fmt(d.get("p50"), 0)} ms, p95={_fmt(d.get("p95"), 0)} ms (n={d["n"]})'
                  for name, d in warm.items()]
        lines.append(f'- provider attempts: {latency["provider_calls"]["total_attempts"]}, failed: '
                     f'{latency["provider_calls"]["failed_attempts"]}, questions with retry: {latency["provider_calls"]["questions_with_retry"]}')
        lines.append(f'- {latency["note"]}')
    elif offline:
        lines += [f'- offline {k}: p50={_fmt(v.get("p50"), 2)} ms, p95={_fmt(v.get("p95"), 2)} ms (n={v["n"]})'
                  for k, v in offline['latency'].items()]
    lines += ['', '## Thresholds', '', *[f'- {k}: {v}' for k, v in meta['thresholds'].items()],
              '', 'Rationale: evaluation/README.md. Average score is the primary signal; pass rate is secondary.',
              '', '## Limitations', '',
              '- One public-domain source (13.5 min, 22 chunks); results do not generalise beyond it.',
              '- Goldens were authored by Claude Opus 5.5 and checked by exact-substring validation; human review is pending.',
              '- A single LLM judge run; judge variance is not yet measured.',
              '- Free generation routes vary by availability; per-case models are in test_case_results.json.',
              '', '## Reproduce', '', 'See evaluation/README.md.', '']
    return '\n'.join(lines)


def _failures_md(rows, judge, adversarial):
    lines = ['# Failure analysis', '']
    if not rows:
        lines += ['Answer stage not run: no app answers were captured, so no request, behaviour or citation '
                  'failures can be reported.', '']
    errors = [r for r in rows if r['error']]
    empty = ['None.'] if rows else ['Not run.']
    lines += ['## Request errors', ''] + ([f'- {r["id"]}: {r["error"]["type"]}' for r in errors] or empty) + ['']
    behavior = [r for r in rows if 'behavior' in r and not r['behavior']['correct']]
    lines += ['## Answer/abstain behaviour failures', '']
    lines += [f'- **{r["id"]}** ({r["category"]}): {r["behavior"]["reason"]}. Q: {r["question"]} A: {r.get("answer", "(no answer: request failed)")[:300]}'
              for r in behavior] or empty
    bad_cites = [r for r in rows if 'citation_check' in r and not r['citation_check']['all_valid']]
    lines += ['', '## Invalid citations', ''] + ([f'- {r["id"]}: {r["citation_check"]["details"]}' for r in bad_cites] or empty)
    lines += ['', '## DeepEval metric failures', '']
    found = False
    for stage, stage_rows in judge.items():
        for row in stage_rows:
            for m in row['metrics']:
                if m['error'] or not m['success']:
                    found = True
                    detail = f'error: {m["error"]}' if m['error'] else f'score {_fmt(m["score"])} < {m["threshold"]}: {(m["reason"] or "")[:400]}'
                    lines.append(f'- [{stage}] {row["name"]} / {m["name"]}: {detail}')
    if not found:
        lines.append('None.' if judge else 'Judge not run.')
    sanity = judge.get('sanity')
    if sanity:
        lines += ['', '## Judge sanity controls (should FAIL)', '']
        lines += [f'- {r["name"]}: ' + ', '.join(f'{m["name"]}={_fmt(m["score"])}' for m in r['metrics']) for r in sanity]
    if adversarial:
        lines += ['', '## Adversarial structure cases', '']
        lines += [f'- {a["name"]}: expected {a["expected"]}, got {a["outcome"]} -> {"pass" if a["passed"] else "FAIL"}' for a in adversarial]
    return '\n'.join(lines) + '\n'


def _experiments_md(means, comparisons, retrieval, offline):
    lines = ['# Retrieval experiment comparison', '',
             'Variants come from the same captured requests (production defaults unchanged). Metrics use gold chunk ids, k=4. '
             'A difference is reported only when it exceeds the registry tolerance (0.05) and its paired bootstrap 95% CI excludes 0.', '']
    if means:
        lines += ['| Variant | recall@4 | MRR | nDCG@4 | hit@4 |', '|---|---|---|---|---|']
        lines += [f'| {n} | {_fmt(m.get("recall"))} | {_fmt(m.get("mrr"))} | {_fmt(m.get("ndcg"))} | {_fmt(m.get("hit"))} |'
                  for n, m in means.items()]
        lines += ['', '## Versus production (hybrid_rerank), recall@4', '']
        for name, c in comparisons.items():
            b = c['bootstrap']
            lines.append(f'- {name}: {c["verdict_for_variant"]}' + (f' (mean diff {b["mean_diff"]:+.3f}, 95% CI '
                         f'[{b["ci95"][0]:+.3f}, {b["ci95"][1]:+.3f}], n={b["n"]})' if b else ''))
        lines += ['', '## Candidate pool recall', ''] + [f'- {k}: {_fmt(v)}' for k, v in retrieval['candidate_recall'].items()]
    else:
        lines.append('Production capture not run; only offline variants below.')
    if offline:
        lines += ['', '## Offline variants (local only)', '']
        lines += [f'- {n}: recall@4={_fmt(m.get("recall"))}, MRR={_fmt(m.get("mrr"))}, nDCG@4={_fmt(m.get("ndcg"))}'
                  for n, m in offline['ir'].items()]
        if offline.get('comparison'):
            c = offline['comparison']
            b = c['bootstrap']
            lines.append(f'- bm25_rerank vs bm25_only: {c["verdict"]}' + (f' (mean diff {b["mean_diff"]:+.3f}, 95% CI '
                         f'[{b["ci95"][0]:+.3f}, {b["ci95"][1]:+.3f}])' if b else ''))
    return '\n'.join(lines) + '\n'


def offline_results(goldens, documents):
    cases = experiments.offline_variants(goldens, documents)
    means, per_case = experiments.ir_table(cases, variants=experiments.OFFLINE_VARIANTS)
    ids = [i for i in per_case['bm25_only'] if per_case['bm25_only'][i] and per_case['bm25_rerank'][i]]
    a = [per_case['bm25_only'][i]['recall'] for i in ids]
    b = [per_case['bm25_rerank'][i]['recall'] for i in ids]
    from evaluation.metrics import registry
    verdict = registry.compare('ir.bm25_rerank.recall', statistics.fmean(a), statistics.fmean(b)) if a else 'n/a'
    ci = experiments.paired_bootstrap(a, b)
    if ci and verdict not in ('flat', 'n/a') and ci['ci95'][0] <= 0 <= ci['ci95'][1]:
        verdict = 'not significant'
    return {'ir': means, 'comparison': {'verdict': verdict, 'bootstrap': ci},
            'latency': {'sparse_ms': distribution([c['timings']['sparse_ms'] for c in cases]),
                        'rerank_ms': distribution([c['timings']['rerank_ms'] for c in cases])},
            'cases': [{'id': c['golden']['id'], **c['contexts'], 'gold': c['golden']['gold_chunk_ids']} for c in cases]}
