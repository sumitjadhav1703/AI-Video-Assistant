# Evaluation summary

- Generated: 2026-11-13T13:01:59+00:00
- Mode: **local** (local execution, remote inference)
- DeepEval: 4.3.4
- Dataset: 45 goldens from `nasa-cop26-stgermain` (public-domain NASA talk)
- Answers captured: 45
- Generator models observed: gemini:gemini/gemini-2.5-flash, groq:groq/openai/gpt-oss-20b, nvidia_nim:nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b, openrouter:openrouter/nvidia/nemotron-3.5-lightning:free
- Judge: meta/muse-spark-1.3; judge spend recorded: $5.6087

## DeepEval (LLM-as-a-judge)

### generation

| Metric | Threshold | Avg | Min | Max | Passed | Failed | Errors |
|---|---|---|---|---|---|---|---|
| Faithfulness | 0.8 | 1.000 | 1.000 | 1.000 | 32 | 0 | 0 |
| Answer Relevancy | 0.7 | 0.986 | 0.700 | 1.000 | 32 | 0 | 0 |
| Contextual Relevancy | 0.5 | 0.237 | 0.000 | 0.647 | 4 | 28 | 0 |
| Contextual Precision | 0.7 | 0.924 | 0.333 | 1.000 | 28 | 4 | 0 |
| Contextual Recall | 0.7 | 0.938 | 0.000 | 1.000 | 30 | 2 | 0 |

### retrieval_pre_rerank

| Metric | Threshold | Avg | Min | Max | Passed | Failed | Errors |
|---|---|---|---|---|---|---|---|
| Contextual Relevancy | 0.5 | 0.126 | 0.000 | 0.396 | 0 | 32 | 0 |
| Contextual Precision | 0.7 | 0.877 | 0.333 | 1.000 | 25 | 6 | 1 |
| Contextual Recall | 0.7 | 1.000 | 1.000 | 1.000 | 32 | 0 | 0 |

### sanity

| Metric | Threshold | Avg | Min | Max | Passed | Failed | Errors |
|---|---|---|---|---|---|---|---|
| Faithfulness | 0.8 | 0.000 | 0.000 | 0.000 | 0 | 2 | 0 |
| Answer Relevancy | 0.7 | 0.000 | 0.000 | 0.000 | 0 | 1 | 0 |
| Contextual Recall | 0.7 | 0.000 | 0.000 | 0.000 | 0 | 1 | 0 |

## Application checks (deterministic, separate from DeepEval)

- cases_with_result: 43
- cases_with_error: 2
- structure_validity: 1.000
- citations_total: 56
- citation_validity: 1.000
- citation_exact_quote_rate: 1.000
- citation_timestamp_match_rate: 1.000
- answered_with_gold_citation_rate: 1.000
- behavior_accuracy: 0.956
- adversarial_cases: 15
- adversarial_pass_rate: 1.000
- abstention: true_abstentions=6, false_abstentions=0, missed_abstentions=0, abstention_precision=1.000, abstention_recall=1.000, abstention_f1=1.000, false_abstention_rate=0.000

## Retrieval (gold chunk ids, k=4)

| Variant | n | hit | recall | precision | MRR | nDCG |
|---|---|---|---|---|---|---|
| dense_only | 37 | 1.000 | 1.000 | 0.358 | 0.946 | 0.951 |
| bm25_only | 37 | 1.000 | 0.892 | 0.297 | 0.867 | 0.826 |
| hybrid_rrf | 37 | 1.000 | 0.964 | 0.338 | 0.928 | 0.909 |
| hybrid_rerank | 37 | 1.000 | 0.977 | 0.345 | 0.892 | 0.897 |

Offline (local BM25 and TinyBERT only):

- bm25_only: recall=0.897, MRR=0.861, nDCG=0.827 (n=39)
- bm25_rerank: recall=0.974, MRR=0.885, nDCG=0.894 (n=39)

## Latency

- dense_retrieval: p50=5 ms, p95=6 ms (n=42)
- sparse_retrieval: p50=1 ms, p95=1 ms (n=42)
- rrf: p50=0 ms, p95=0 ms (n=42)
- rerank: p50=8 ms, p95=10 ms (n=42)
- generation: p50=2016 ms, p95=3694 ms (n=52)
- end_to_end: p50=2084 ms, p95=5128 ms (n=40)
- provider attempts: 57, failed: 0, questions with retry: 7
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
