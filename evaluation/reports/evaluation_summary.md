# Evaluation summary

- Generated: 2026-11-13T12:08:59+00:00
- Mode: **offline** (fully offline (no external inference))
- DeepEval: 4.3.4
- Dataset: 45 goldens from `nasa-cop26-stgermain` (public-domain NASA talk)
- Answers captured: 0
- Generator models observed: none (answer stage not run)
- Judge: not run; judge spend recorded: $0.0000

## DeepEval (LLM-as-a-judge)

Not run. No DeepEval scores exist for this report; none are estimated.

## Application checks (deterministic, separate from DeepEval)

- cases_with_result: 0
- cases_with_error: 0
- structure_validity: —
- citations_total: 0
- citation_validity: —
- citation_exact_quote_rate: —
- citation_timestamp_match_rate: —
- answered_with_gold_citation_rate: —
- behavior_accuracy: —
- adversarial_cases: 15
- adversarial_pass_rate: 1.000
- abstention: true_abstentions=0, false_abstentions=0, missed_abstentions=0, abstention_precision=—, abstention_recall=—, abstention_f1=—, false_abstention_rate=—

## Retrieval (gold chunk ids, k=4)

Production capture not run.

Offline (local BM25 and TinyBERT only):

- bm25_only: recall=0.897, MRR=0.861, nDCG=0.827 (n=39)
- bm25_rerank: recall=0.974, MRR=0.885, nDCG=0.894 (n=39)

## Latency

- offline sparse_ms: p50=0.67 ms, p95=1.12 ms (n=45)
- offline rerank_ms: p50=7.57 ms, p95=9.18 ms (n=45)

## Thresholds

- Faithfulness: 0.8
- Answer Relevancy: 0.7
- Contextual Precision: 0.7
- Contextual Recall: 0.7
- Contextual Relevancy: 0.5

Rationale: evaluation/README.md. Average score is the primary signal; pass rate is secondary.

## Limitations

- One public-domain source (13.5 min, 22 chunks); results do not generalise beyond it.
- Goldens were authored by Claude Opus 5.5 and checked by exact-substring validation; human review is pending.
- A single LLM judge run; judge variance is not yet measured.
- Free generation routes vary by availability; per-case models are in test_case_results.json.

## Reproduce

See evaluation/README.md.
