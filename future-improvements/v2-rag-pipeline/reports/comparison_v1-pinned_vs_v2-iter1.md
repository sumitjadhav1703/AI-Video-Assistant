# Comparison: v1-pinned vs v2-iter1

Paired over 31 goldens answered in both runs; DeepEval over 26 judged in both. Same dataset, same pinned generator, same embedding model.

## Deterministic (whole paired set)

| Metric | v1-pinned | v2-iter1 |
|---|---|---|
| behaviour_accuracy | 0.839 | 1.000 |
| request_errors_503 | 5 | 0 |
| rejected_model_outputs | 5 | 0 |
| provider_attempts | 31 | 31 |
| citation validity | 1.000 (37) | 1.000 (48) |
| abstention F1 | — | — |

## DeepEval (paired, judge meta/muse-spark-1.3)

| Metric | v1-pinned | v2-iter1 | Δ (95% CI) | n |
|---|---|---|---|---|
| Faithfulness | 1.000 | 1.000 | +0.000 [+0.000, +0.000] | 25 |
| Answer Relevancy | 0.981 | 0.941 | -0.040 [-0.136, +0.038] | 26 |
| Contextual Precision | 0.920 | 0.933 | +0.013 [-0.042, +0.080] | 26 |
| Contextual Recall | 1.000 | 0.981 | -0.019 [-0.058, +0.000] | 26 |
| Contextual Relevancy | 0.251 | 0.273 | +0.022 [-0.017, +0.061] | 26 |

Judged in only one run (the other produced no answer): v1-pinned: none; v2-iter1: ['NASA-E-003', 'NASA-F-004', 'NASA-H-005', 'NASA-M-003', 'NASA-M-004', 'NASA-M-005'].

## Retrieval

- quote coverage@4 (production hybrid + rerank): v1-pinned 1.000 vs v2-iter1 0.974, Δ -0.026 [-0.064, +0.000], n=26

## Latency (paired: warm questions both versions answered)

- v1-pinned: e2e p50 1939 ms, p95 4519 ms; generation p50 1866 ms, p95 4446 ms; answer length p50 40 chars (n=24 questions answered by both)
- v2-iter1: e2e p50 2256 ms, p95 6289 ms; generation p50 2154 ms, p95 6195 ms; answer length p50 82 chars (n=24 questions answered by both)

## Gate (pre-registered)

| Must hold | Result |
|---|---|
| faithfulness_not_worse | pass |
| answer_relevancy_not_worse | pass |
| citation_validity_100 | pass |
| abstention_f1_not_worse | pass |
| quote_coverage_not_worse | pass |
| latency_p95_within_25pct | FAIL |

| Primary improvement (at least one) | Result |
|---|---|
| fewer_rejected_outputs | yes |
| fewer_503s | yes |
| higher_behaviour_accuracy | yes |
| contextual_precision_or_recall_beyond_noise | no |

**Verdict: v2-iter1 is NOT shown to be better than v1-pinned.**
