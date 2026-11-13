# Retrieval experiment comparison

Variants come from the same captured requests (production defaults unchanged). Metrics use gold chunk ids, k=4. A difference is reported only when it exceeds the registry tolerance (0.05) and its paired bootstrap 95% CI excludes 0.

| Variant | recall@4 | MRR | nDCG@4 | hit@4 |
|---|---|---|---|---|
| dense_only | 1.000 | 0.946 | 0.951 | 1.000 |
| bm25_only | 0.892 | 0.867 | 0.826 | 1.000 |
| hybrid_rrf | 0.964 | 0.928 | 0.909 | 1.000 |
| hybrid_rerank | 0.977 | 0.892 | 0.897 | 1.000 |

## Versus production (hybrid_rerank), recall@4

- dense_only: flat (mean diff +0.023, 95% CI [+0.000, +0.059], n=37)
- bm25_only: regressed (mean diff -0.086, 95% CI [-0.144, -0.032], n=37)
- hybrid_rrf: flat (mean diff -0.014, 95% CI [-0.041, +0.000], n=37)

## Candidate pool recall

- dense@10: 1.000
- bm25@10: 0.973
- fused@12: 1.000

## Offline variants (local only)

- bm25_only: recall@4=0.897, MRR=0.861, nDCG@4=0.827
- bm25_rerank: recall@4=0.974, MRR=0.885, nDCG@4=0.894
- bm25_rerank vs bm25_only: improved (mean diff +0.077, 95% CI [+0.026, +0.141])
