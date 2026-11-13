"""Gate / guardrail / info rules for comparing two runs (adapted from the rag-eval-deepeval reference).

A regression counts only if the worsening exceeds max(tol, rel_tol * |baseline|). Judge metrics are
compared on average score; pass rate is info because it jumps when scores cluster near the threshold.
Tolerances are provisional until two identical runs measure the real noise floor.
"""
QUALITY_GUARD = {'direction': 'higher', 'kind': 'guardrail', 'tol': 0.05, 'rel_tol': 0.0}
DETERMINISTIC_GATE = {'direction': 'higher', 'kind': 'gate', 'tol': 0.0, 'rel_tol': 0.0}
IR_GUARD = {'direction': 'higher', 'kind': 'guardrail', 'tol': 0.05, 'rel_tol': 0.0}
LATENCY_GUARD = {'direction': 'lower', 'kind': 'guardrail', 'tol': 0.0, 'rel_tol': 0.25}
INFO = {'direction': 'higher', 'kind': 'info', 'tol': 0.0, 'rel_tol': 0.0}


def rule_for(metric_id):
    if metric_id.startswith('deepeval.') and metric_id.endswith('.avg_score'):
        return QUALITY_GUARD
    if metric_id in ('deterministic.citation_validity', 'deterministic.structure_validity',
                     'deterministic.adversarial_pass_rate', 'deterministic.behavior_accuracy'):
        return DETERMINISTIC_GATE
    if metric_id.startswith('ir.') and metric_id.rsplit('.', 1)[-1] in ('recall', 'mrr', 'ndcg', 'hit'):
        return IR_GUARD
    if metric_id.startswith('latency.') and metric_id.endswith('p95_ms'):
        return LATENCY_GUARD
    return INFO


def compare(metric_id, baseline, candidate):
    """-> 'improved' | 'flat' | 'regressed' | 'n/a' using the metric's direction and tolerance."""
    if baseline is None or candidate is None:
        return 'n/a'
    rule = rule_for(metric_id)
    delta = candidate - baseline if rule['direction'] == 'higher' else baseline - candidate
    tolerance = max(rule['tol'], rule['rel_tol'] * abs(baseline))
    if delta > tolerance:
        return 'improved'
    if delta < -tolerance:
        return 'regressed'
    return 'flat'
