# Upgrade roadmap status

Handoff updated November 14, 2026 for `main` (PR #7 merged, commit `60598c8`). The stack is deployed and live. Start with [AGENTS.md](../AGENTS.md) in `~/Projects/AI-Video-Assistant`. The current retrieval implementation uses pgvector and BM25, RRF, and mandatory FlashRank reranking. The earlier implementation plan and planning brief were removed; read them with `git show dfa7e60:UPGRADE_IMPLEMENTATION_PLAN.md` and `git show dfa7e60:AI_VIDEO_ASSISTANT_CODEX_PLANNING_BRIEF.md`. Deployment follows [SUBMISSION_GUIDELINES.md](../SUBMISSION_GUIDELINES.md); results are recorded in [DEPLOYMENT_REPORT.md](../DEPLOYMENT_REPORT.md).

| Workstream | Status |
| --- | --- |
| Safety and rate limiting | Implemented. PostgreSQL enforces shared, per-client and per-job limits, token-owned processing/chat slots, and provider attempt, text and audio budgets. Media and prompts are bounded. Inference defaults to disabled. |
| LangChain and LiteLLM | Implemented the in-process Router, economy/strong tiers, and application-owned fallback accounting. Gemini and Groq passed intercepted-HTTP SDK tests. The deployed Render service runs with provider calls enabled (`DEMO_LIVE_MODE=public`). |
| Embedding routes | New indexes use the configured free route order. If a route temporarily fails during indexing, the fallback embeds the full job before publishing its index. Chat pins the persisted embedding route and dimension. The two Nemotron trial routes are disabled on Render. |
| Minutes UI | The original upload workspace opens at `/` with three bundled spoken demo clips (MP3). Desktop results place chat alongside the summary and findings. Mobile shows chat first. The collapsed transcript follows both. The `/eval`, `/usage` and `/pipeline` pages explain evaluation, limits and pipeline; the old `/sample` page is removed. |
| Privacy and provenance | Implemented text identifier redaction, sanitized chunks, stable job-scoped IDs, timestamp precision labels, structured findings, and validation of chat citations against retrieved passages. Existing embedding spaces remain separate. |
| Hybrid retrieval | Implemented ten dense and ten BM25 candidates, deterministic RRF, up to twelve unique reranker candidates, and up to four final passages. Reranker failure stops generation. |
| Restart recovery | Added explicit, fenced operator recovery for stale processing/chat reservations, and actionable interrupted status in the web app. Users retry by starting a new analysis. |
| Performance measurement | Added content-free stage timings and counts. Compared retrieval stages with actual local embeddings and ran an isolated browser audio experiment. Neither experiment adds a production dependency. |
| Evaluation and release | DeepEval evaluation done ([report](../evaluation/EVALUATION_REPORT.md)); stack deployed manually ([DEPLOYMENT_REPORT.md](../DEPLOYMENT_REPORT.md)). Open gates below. Live measurements: [LIVE_PERFORMANCE.md](LIVE_PERFORMANCE.md). |

## Verified locally

- The multi-provider update passed 213 backend tests with PostgreSQL 16 and pgvector 0.8.1. The Linux ARM64 workload peaked at 365.96 MiB under the 512 MiB, zero-swap, 0.1-CPU cap. Three 120-second clips completed upload, grounded chat, and cleanup with intercepted provider HTTP. [Benchmark record](RECRUITER_DEMO.md#local-verification)
- Seven frontend tests and the Vite production build passed after the UI update. Chrome with intercepted requests verified demo selection, explicit upload, progress, results, chat citations, refresh, deletion, and chat above the fold at 320 px and 1082 px. The offline sample loaded and sought to citations with backend access blocked.
- Native AMD64 CI on `main` passed (backend gate, frontend, MCP; run 43466550591, per the deployment report preflight). The ARM64 results above measure a separate architecture.

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

## Release gates

Done:

1. Native AMD64 validation on `main`, including the backend gate in the built image. [Run 43466550591](../DEPLOYMENT_REPORT.md)
2. DeepEval relevance and answer evaluation. [Evaluation report](../evaluation/EVALUATION_REPORT.md)
3. Hosted deployment and checks for Render, Vercel, Cloudflare and Neon, done manually with [SUBMISSION_GUIDELINES.md](../SUBMISSION_GUIDELINES.md); results in [DEPLOYMENT_REPORT.md](../DEPLOYMENT_REPORT.md). The GitHub release automation (`DEPLOY_SAMPLE_STACK`) stays off. The daily cleanup workflow ran successfully.

Still open:

1. Proxy-IP attribution on Render is unverified. A shared proxy identity would let one visitor use the global per-client allowance. Check `/usage` from a second network.
2. Live smoke test by the owner (a short English clip and one chat question on the Vercel site), then record the result in `DEPLOYMENT_REPORT.md`.
3. Review account-specific data terms, free limits and overage controls for every selected STT, generation and embedding route, since public mode now sends visitor audio to those providers. [Provider configuration](HYBRID_IMPLEMENTATION.md#provider-and-release-gates)
4. Render `healthCheckPath` is empty; set it to `/health` in the dashboard. `scripts/release_worker.mjs` rejects the wrangler OAuth token format. A processing slot stuck after a restart needs `python -m backend.recover` (runbook above).
5. Act on findings in [LIVE_PERFORMANCE.md](LIVE_PERFORMANCE.md). [Release order](RECRUITER_DEMO.md#release-order)
