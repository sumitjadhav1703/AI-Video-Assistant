# Upgrade roadmap status

Reviewed 2026-11-11 on `work/project-updates`. The approved revision specifies LangChain PGVector and BM25, RRF, then mandatory FlashRank reranking. It supersedes the earlier FTS and optional-reranking proposals in the [implementation plan](../UPGRADE_IMPLEMENTATION_PLAN.md) and [planning brief](../AI_VIDEO_ASSISTANT_CODEX_PLANNING_BRIEF.md).

| Workstream | Status |
| --- | --- |
| Safety and rate limiting | Implemented. PostgreSQL enforces shared, per-client and per-job limits, token-owned processing/chat slots, and provider attempt, text and audio budgets. Media and prompts are bounded. Inference defaults to disabled. |
| LangChain and LiteLLM | Implemented the in-process Router, economy/strong tiers, and application-owned fallback accounting. Gemini and Groq passed intercepted-HTTP SDK tests. Live generation remains disabled pending account verification. |
| Privacy and provenance | Implemented text identifier redaction, sanitized chunks, stable job-scoped IDs, timestamp precision labels, structured findings, and validation of chat citations against retrieved passages. Existing embedding spaces remain separate. |
| Hybrid retrieval | Implemented ten dense and ten BM25 candidates, deterministic RRF, up to twelve unique reranker candidates, and up to four final passages. Reranker failure stops generation. |
| Restart recovery | Added explicit, fenced operator recovery for stale processing/chat reservations, and actionable interrupted status in the web app. Users retry by starting a new analysis. |
| Performance measurement | Added content-free stage timings and counts. Compared retrieval stages with actual local embeddings and ran an isolated browser audio experiment. Neither experiment adds a production dependency. |
| Evaluation and release | Pending the gates below. |

All 162 backend tests passed, including PostgreSQL 16, pgvector 0.8.1, real FlashRank inference and intercepted Gemini-to-Groq failover. Four frontend tests and the production frontend build passed. A Playwright test exercised interrupted-job messaging and the Start over action using intercepted requests. A separate loopback Uvicorn check verified that the request path was absent from the server log.

## Recovery after an interrupted process

Use a private terminal with the intended `DATABASE_URL` exported. Inspection returns bearer job IDs and owner tokens. Stop all workers that could hold the reservation and suspend admissions before running recovery. Apply the additive reservation timestamp schema with all old workers stopped to avoid mixed-version writes.

```sh
python -m backend.recover inspect
python -m backend.recover recover processing --all-workers-stopped
# For a stale chat reservation, use "chat" in place of "processing".
```

The CLI prompts for the exact token without echo. It requires 30 minutes since reservation and, for processing, since the latest job update. Age alone cannot prove worker shutdown. Recovery marks queued/running jobs `interrupted` and releases the matching reservation in one transaction. It retains the last stage, completed results and usage counters. If PostgreSQL committed completion but the worker lost the acknowledgment, the worker keeps the index and reservation until recovery. Existing delete/cleanup can remove interrupted records and partial indexes. A new analysis uses fresh admission and quota. Automatic replay and mid-stage resume would require durable input and provider idempotency.

## Measurements and decisions

- Server telemetry records ASGI body bytes and read time, staged file size and copy time, media conversion, per-chunk and total transcription, embeddings/indexing, retrieval stage times and time to persisted results. The provider ledger records attempts, reported usage where available, and elapsed time. ASGI timings exclude browser/proxy transfer outside the application. Uvicorn access logs are disabled in the container and documented launch command to protect bearer job IDs. Billing and hosted CPU/memory require separate measurement.
- Browser extraction worked on three synthetic clips and saved about 3% of their original bytes. The prototype stays outside the app pending representative media, lower-powered device tests, full transfer/memory measurements and distribution review. [Browser experiment](BROWSER_MEDIA_EXPERIMENT.md)
- Local BGE-small recall at four was 1.000 dense, 0.917 after fusion and 0.833 after reranking across 12 synthetic questions. Keep local embeddings out of the hosted service. Use representative labels before retuning required reranking. [Retrieval benchmark](BENCHMARK_NOTES.md#optional-local-embedding-experiment)

## Remaining release gates

1. Verify model allowances, usage limits, data terms, and overage controls for the [configured routes](HYBRID_IMPLEMENTATION.md#provider-and-release-gates) and new Singapore accounts. Verify `gemini-embedding-001` at 768 dimensions and Groq Whisper Large V3 Turbo for English transcription. Sarvam and YouTube remain off by default. [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) · [Groq limits](https://console.groq.com/docs/rate-limits) · [Render Free](https://render.com/docs/free) · [Neon plans](https://neon.com/docs/introduction/plans)
2. Verify NVIDIA trial access with an approved private synthetic test. Verify Meta pricing and the shared ledger before enabling its owner-only switch. See the [Singapore cutover and release gates](RECRUITER_DEMO.md#release-order).
3. Build and exercise the backend in a Linux container capped at 512 MiB, including bounded upload/FFmpeg, indexing and chat with mocked providers. The existing import and reranker stress script is a preliminary check. The macOS full-import result of 444.6 MiB cannot establish Linux or full-workload fit. Verify proxy attribution, edge protection, and migration/rollback before public rollout. [Benchmark commands](BENCHMARK_NOTES.md)
4. Run representative relevance and answer evaluation when `rag-eval-deepeval-main`, labelled permissible material, and a free/local judge strategy are available. Browser Whisper, parallel STT and prompt consolidation remain optional until measured against a representative baseline.

See the [hybrid implementation guide](HYBRID_IMPLEMENTATION.md) for provider configuration and the [local backend suite](../output/validation/roadmap-tests.log) for current test evidence.
