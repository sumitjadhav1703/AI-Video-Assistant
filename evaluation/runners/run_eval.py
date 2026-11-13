"""Evaluation CLI. Run from the repository root with the isolated venv:

  evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode offline
  evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage index
  evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage answer --scope owner
  evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage probe
  evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage judge --pilot 3
  evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage judge
  evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage report
"""
import argparse
import json
import os
import sys

from evaluation import config
from evaluation.runners import guards

STAGES = ('index', 'answer', 'probe', 'judge', 'report')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Evaluate the existing AI Video Assistant RAG pipeline.')
    parser.add_argument('--mode', choices=('local', 'offline'), required=True)
    parser.add_argument('--stage', choices=STAGES + ('all',), default='report')
    parser.add_argument('--scope', choices=('public', 'owner'), default='public',
                        help='operation grant for generation; owner adds free owner-only routes, never paid ones')
    parser.add_argument('--ids', nargs='*', help='only these golden ids')
    parser.add_argument('--limit', type=int, help='only the first N goldens')
    parser.add_argument('--pilot', type=int, help='judge only the first N eligible cases (cost probe)')
    parser.add_argument('--no-sanity', action='store_true', help='skip the 4 judge sanity controls')
    parser.add_argument('--force', action='store_true', help='re-answer cases that already have results')
    parser.add_argument('--max-concurrent', type=int, default=2)
    args = parser.parse_args(argv)
    if args.mode == 'offline' and args.stage not in ('report', 'all'):
        parser.error('offline mode only runs the local report (BM25, reranker, deterministic checks)')
    return args


def log_run(entry):
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    with (config.RAW_DIR / 'run_log.jsonl').open('a') as handle:
        handle.write(json.dumps(entry, default=str) + '\n')


def selected_goldens(args):
    from evaluation.dataset.validate import RESOLVED_FILE
    goldens = [json.loads(line) for line in RESOLVED_FILE.read_text().splitlines() if line.strip()]
    if args.ids:
        goldens = [g for g in goldens if g['id'] in set(args.ids)]
    return goldens[:args.limit] if args.limit else goldens


def make_judge(budget):
    from evaluation.metrics.judge import MetaJudge, SpendLedger
    return MetaJudge(SpendLedger(budget))


def stage_judge(args):
    from evaluation.metrics import deepeval_suite
    from evaluation.metrics.judge import require_judge_authorisation
    from evaluation.runners import adapter, judge_runner
    budget = require_judge_authorisation()
    if args.pilot:
        budget = min(budget, config.PILOT_BUDGET_USD)
    cases = [c for c in adapter.load_answers().values() if deepeval_suite.eligible(c)]
    if args.ids:
        cases = [c for c in cases if c['golden']['id'] in set(args.ids)]
    if args.pilot:
        cases = cases[:args.pilot]
    if not cases:
        raise SystemExit('No answered cases to judge; run --stage answer first.')
    judge = make_judge(budget)
    out = config.RAW_DIR / ('judge_pilot' if args.pilot else 'judge')
    out.mkdir(parents=True, exist_ok=True)
    with guards.network_guard(guards.allowed_hosts('local', judge=True)):
        for stage in deepeval_suite.STAGES:
            path = out / f'{stage}.json'
            # Resume: keep complete rows from earlier runs, judge only what is missing.
            kept = [r for r in json.loads(path.read_text())
                    if not r.get('missing') and not any(m['error'] for m in r['metrics'])] \
                if path.exists() and not args.force else []
            rows = judge_runner.judge_stage(cases, stage, judge, max_concurrent=args.max_concurrent,
                                            skip={r['name'] for r in kept})
            path.write_text(json.dumps(kept + rows, indent=1))
            missing = sum(1 for r in rows if r.get('missing'))
            print(f'{stage}: {len(kept)} kept, {len(rows)} judged now ({missing} missing); '
                  f'spend so far ${judge.ledger.spent:.4f}')
        if not args.pilot and not args.no_sanity and (args.force or not (out / 'sanity.json').exists()):
            (out / 'sanity.json').write_text(json.dumps(judge_runner.judge_sanity(judge, max_concurrent=args.max_concurrent), indent=1))
    summary = judge.ledger.summary()
    if args.pilot and cases:
        per_case = summary['spent_usd'] / len(cases)
        eligible = sum(deepeval_suite.eligible(c) for c in adapter.load_answers().values())
        summary['projection'] = {'usd_per_case': round(per_case, 5), 'eligible_cases': eligible,
                                 'projected_full_run_usd': round(per_case * eligible, 4)}
    print(json.dumps(summary, indent=2))
    log_run({'stage': 'judge', 'pilot': args.pilot, 'cases': len(cases), 'ledger': summary,
             'judge_latency_ms': {'calls': len(judge.latencies_ms)}})


def main(argv=None):
    args = parse_args(argv)
    guards.apply_environment(args.mode)
    stages = STAGES if args.stage == 'all' else (args.stage,)
    if args.mode == 'local' and set(stages) & {'index', 'answer'} and 'DATABASE_URL' not in os.environ:
        raise SystemExit('Set EVAL_DATABASE_URL to the disposable ava-eval-pg database (see evaluation/README.md).')
    goldens = selected_goldens(args)
    for stage in stages:
        if args.mode == 'local' and stage == 'index':
            from evaluation.runners import adapter
            with guards.network_guard(guards.allowed_hosts('local')):
                result = adapter.index()
            print(json.dumps(result, indent=2, default=str))
            log_run({'stage': 'index', **result})
        elif args.mode == 'local' and stage == 'answer':
            from evaluation.runners import adapter
            with guards.network_guard(guards.allowed_hosts('local')):
                run = adapter.answer_all(goldens, scope=args.scope, force=args.force)
            log_run({'stage': 'answer', **run})
            if run['stopped_early']:
                print(f'Stopped early ({run["stopped_early"]["type"]}); rerun the same command later to resume.')
        elif args.mode == 'local' and stage == 'probe':
            from evaluation.metrics.judge import require_judge_authorisation
            judge = make_judge(min(require_judge_authorisation(), config.PILOT_BUDGET_USD))
            with guards.network_guard(guards.allowed_hosts('local', judge=True)):
                result = judge.probe()
            print(json.dumps(result, indent=2))
            log_run({'stage': 'probe', **result})
        elif args.mode == 'local' and stage == 'judge':
            stage_judge(args)
        elif stage == 'report':
            from evaluation.dataset import build_chunks
            from evaluation.metrics.deterministic import adversarial_structure_suite
            from evaluation.runners import report
            documents = build_chunks.build_documents()
            with guards.network_guard(guards.allowed_hosts('offline')):
                adversarial = adversarial_structure_suite(documents)
                offline = report.offline_results(goldens, documents)
            config.RAW_DIR.mkdir(parents=True, exist_ok=True)
            (config.RAW_DIR / 'offline.json').write_text(json.dumps(offline, indent=1))
            metrics = report.write_reports(args.mode, adversarial=adversarial, dataset_size=len(goldens))
            print(f'Reports written to {config.REPORTS_DIR} ({", ".join(report.REPORT_FILES)})')
            print(json.dumps({'answers_captured': metrics['meta']['answers_captured'],
                              'judge_stages': metrics['meta']['stages_run']['judge'],
                              'adversarial_pass_rate': metrics['deterministic']['adversarial_pass_rate'],
                              'offline_ir': offline['ir']}, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
