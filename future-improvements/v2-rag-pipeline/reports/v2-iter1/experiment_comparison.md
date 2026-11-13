# Retrieval experiment comparison

Variants come from the same captured requests (production defaults unchanged). Metrics use gold chunk ids, k=4. A difference is reported only when it exceeds the registry tolerance (0.05) and its paired bootstrap 95% CI excludes 0.

| Variant | quote coverage | recall | MRR | nDCG | hit |
|---|---|---|---|---|---|
| dense_only | 0.943 | 0.941 | 0.943 | 0.916 | 0.974 |
| bm25_only | 0.895 | 0.829 | 0.908 | 0.820 | 0.947 |
| hybrid_rrf | 0.934 | 0.904 | 0.943 | 0.884 | 1.000 |
| hybrid_rerank | 0.954 | 0.914 | 0.936 | 0.886 | 1.000 |
| hybrid_rerank_top5 | 0.971 | 0.936 | 0.936 | 0.897 | 1.000 |
| rrf_rerank_blend | 0.941 | 0.917 | 0.952 | 0.894 | 1.000 |

`hybrid_rerank_top5` is scored at k=5; every other variant at the production k=4.

## Versus production (hybrid_rerank), quote_coverage

- dense_only: not significant (mean diff -0.011, 95% CI [-0.077, +0.033], n=38)
- bm25_only: not significant (mean diff -0.059, 95% CI [-0.138, +0.000], n=38)
- hybrid_rrf: not significant (mean diff -0.020, 95% CI [-0.053, +0.000], n=38)
- hybrid_rerank_top5: not significant (mean diff +0.018, 95% CI [+0.000, +0.044], n=38)
- rrf_rerank_blend: not significant (mean diff -0.013, 95% CI [-0.039, +0.000], n=38)

## Versus production (hybrid_rerank), recall

- dense_only: flat (mean diff +0.026, 95% CI [-0.053, +0.096], n=38)
- bm25_only: regressed (mean diff -0.086, 95% CI [-0.178, -0.013], n=38)
- hybrid_rrf: flat (mean diff -0.011, 95% CI [-0.059, +0.037], n=38)
- hybrid_rerank_top5: flat (mean diff +0.022, 95% CI [+0.000, +0.057], n=38)
- rrf_rerank_blend: flat (mean diff +0.002, 95% CI [-0.039, +0.044], n=38)

## Candidate pool recall

- dense@10: 1.000
- bm25@10: 0.923
- fused@12: 0.987

## Offline variants (local only)

- bm25_only: recall@4=0.833, MRR=0.910, nDCG@4=0.825
- bm25_rerank: recall@4=0.904, MRR=0.938, nDCG@4=0.879
- bm25_rerank vs bm25_only: not significant (mean diff +0.071, 95% CI [+0.000, +0.154])
