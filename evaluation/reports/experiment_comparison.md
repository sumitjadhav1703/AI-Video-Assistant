# Retrieval experiment comparison

Variants come from the same captured requests (production defaults unchanged). Metrics use gold chunk ids, k=4. A difference is reported only when it exceeds the registry tolerance (0.05) and its paired bootstrap 95% CI excludes 0.

Production capture not run; only offline variants below.

## Offline variants (local only)

- bm25_only: recall@4=0.897, MRR=0.861, nDCG@4=0.827
- bm25_rerank: recall@4=0.974, MRR=0.885, nDCG@4=0.894
- bm25_rerank vs bm25_only: improved (mean diff +0.077, 95% CI [+0.026, +0.141])
