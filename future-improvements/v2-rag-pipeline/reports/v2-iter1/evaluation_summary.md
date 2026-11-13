# Evaluation summary

- Generated: 2026-11-13T14:25:38+00:00
- Mode: **local** (local execution, remote inference)
- DeepEval: 4.3.4
- Dataset: 45 goldens from `nasa-cop26-stgermain` (public-domain NASA talk)
- Answers captured: 44
- Generator models observed: nvidia_nim:nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b
- Judge: meta/muse-spark-1.3; judge spend recorded: $7.6312

## DeepEval (LLM-as-a-judge)

### generation

| Metric | Threshold | Avg | Min | Max | Passed | Failed | Errors |
|---|---|---|---|---|---|---|---|
| Faithfulness | 0.8 | 1.000 | 1.000 | 1.000 | 32 | 0 | 0 |
| Answer Relevancy | 0.7 | 0.952 | 0.000 | 1.000 | 31 | 1 | 0 |
| Contextual Relevancy | 0.5 | 0.288 | 0.053 | 0.692 | 7 | 25 | 0 |
| Contextual Precision | 0.7 | 0.940 | 0.333 | 1.000 | 29 | 3 | 0 |
| Contextual Recall | 0.7 | 0.938 | 0.000 | 1.000 | 29 | 3 | 0 |

## Application checks (deterministic, separate from DeepEval)

- cases_with_result: 44
- cases_with_error: 0
- structure_validity: 1.000
- citations_total: 56
- citation_validity: 1.000
- citation_exact_quote_rate: 1.000
- citation_timestamp_in_range_rate: 1.000
- answered_with_gold_citation_rate: 1.000
- behavior_accuracy: 1.000
- adversarial_cases: 19
- adversarial_pass_rate: 1.000
- abstention: true_abstentions=6, false_abstentions=0, missed_abstentions=0, abstention_precision=1.000, abstention_recall=1.000, abstention_f1=1.000, false_abstention_rate=0.000

## Retrieval (gold chunk ids, k=4)

| Variant | n | quote coverage | hit | recall | precision | MRR | nDCG |
|---|---|---|---|---|---|---|---|
| dense_only | 38 | 0.943 | 0.974 | 0.941 | 0.428 | 0.943 | 0.916 |
| bm25_only | 38 | 0.895 | 0.947 | 0.829 | 0.362 | 0.908 | 0.820 |
| hybrid_rrf | 38 | 0.934 | 1.000 | 0.904 | 0.395 | 0.943 | 0.884 |
| hybrid_rerank | 38 | 0.954 | 1.000 | 0.914 | 0.401 | 0.936 | 0.886 |
| hybrid_rerank_top5 | 38 | 0.971 | 1.000 | 0.936 | 0.332 | 0.936 | 0.897 |
| rrf_rerank_blend | 38 | 0.941 | 1.000 | 0.917 | 0.401 | 0.952 | 0.894 |

Quote coverage = share of gold evidence quotes inside the top-k chunks; it does not depend on chunk ids, so it is the metric to compare across chunking versions.

Offline (local BM25 and TinyBERT only):

- bm25_only: recall=0.833, MRR=0.910, nDCG=0.825 (n=39)
- bm25_rerank: recall=0.904, MRR=0.938, nDCG=0.879 (n=39)

## Latency

- dense_retrieval: p50=8 ms, p95=18 ms (n=43)
- sparse_retrieval: p50=1 ms, p95=1 ms (n=43)
- rrf: p50=0 ms, p95=0 ms (n=43)
- rerank: p50=8 ms, p95=15 ms (n=43)
- generation: p50=2189 ms, p95=6703 ms (n=43)
- end_to_end: p50=2286 ms, p95=6782 ms (n=43)
- provider attempts: 44, failed: 0, questions with retry: 0
- Query embeddings were fetched in one batched request and served from cache, so dense_retrieval measures the pgvector search only. Cold = first measured question of a run (excluded from warm stats).

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
