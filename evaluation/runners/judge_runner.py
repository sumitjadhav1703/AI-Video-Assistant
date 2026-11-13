"""Run DeepEval metrics over captured app output with the capped Meta judge."""
from deepeval import evaluate
from deepeval.evaluate.configs import AsyncConfig, CacheConfig, DisplayConfig, ErrorConfig

from evaluation.metrics import deepeval_suite


def _configs(max_concurrent):
    return dict(async_config=AsyncConfig(run_async=True, max_concurrent=max_concurrent),
                display_config=DisplayConfig(print_results=False, show_indicator=True, inspect_after_run=False),
                cache_config=CacheConfig(write_cache=False, use_cache=False),
                # A refused (over-budget) or failed judge call becomes a recorded metric error, never a score.
                error_config=ErrorConfig(ignore_errors=True, skip_on_missing_params=False))


def extract(result):
    rows = []
    for test in getattr(result, 'test_results', None) or []:
        rows.append({'name': test.name, 'success': test.success, 'metrics': [
            {'name': m.name, 'score': m.score, 'success': m.success, 'threshold': m.threshold,
             'reason': m.reason, 'error': m.error, 'evaluation_model': m.evaluation_model}
            for m in (test.metrics_data or [])]})
    return rows


def judge_stage(cases, stage, judge, *, max_concurrent=2):
    test_cases = [tc for c in cases if deepeval_suite.eligible(c)
                  for tc in [deepeval_suite.build_test_case(c, stage)] if tc is not None]
    if not test_cases:
        return []
    metrics = deepeval_suite.build_metrics(judge, deepeval_suite.stage_metric_names(stage))
    return extract(evaluate(test_cases=test_cases, metrics=metrics, **_configs(max_concurrent)))


def judge_sanity(judge, *, max_concurrent=2):
    rows = []
    for spec, test_case in deepeval_suite.sanity_test_cases():
        metrics = deepeval_suite.build_metrics(judge, [spec['metric']])
        rows += extract(evaluate(test_cases=[test_case], metrics=metrics, **_configs(max_concurrent)))
    return rows
