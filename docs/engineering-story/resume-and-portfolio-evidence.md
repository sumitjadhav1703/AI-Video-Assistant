# Resume and portfolio evidence

Purpose: resume bullets and interview talking points for AI Video Assistant, each tied to the tracked file that holds the number and to a status, with the conditions stated so nothing is overclaimed.

**Status legend:** **Implemented** = code exists. **Verified** = tested or measured, number in a tracked source. **Planned** = not started. **Experimental** = built, not adopted. **Not implemented** = does not exist. **Not measured** = no evidence.

**Standing conditions (apply to every number unless the bullet says otherwise).**
- Memory and startup figures: Linux arm64 (Colima), 512 MiB, no swap, 0.1 CPU, n=1 run per image, one 120-second synthetic clip, mocked provider HTTP. Not a hosted Render measurement.
- Quality figures: one public-domain source (NASA COP26 talk, 22 chunks), 45 questions, 32 judged answerable, one judge model, one run, goldens written by an AI and not yet human-reviewed.
- No baseline was ever measured for the original app, so there are no "before vs after" claims for latency or answer quality against it.

## 1. Technical achievements

- **Built a transcript question-answering service whose answers must cite exact transcript quotes with timestamps, and which abstains otherwise.** Evidence: 56/56 citations valid (in context, exact quote, matching timestamps); abstention precision, recall and F1 = 1.0 on the 6 unanswerable questions, 0 false abstentions. Source: [EVALUATION_REPORT §4.2](../../evaluation/EVALUATION_REPORT.md), [metrics.json](../../evaluation/reports/metrics.json). Status: Implemented, Verified. Conditions: one source, n=45.
- **Evaluated generation with DeepEval and measured faithfulness of 1.000 on 32 judged answers.** Evidence: Faithfulness avg 1.000, 32/32 pass; Answer Relevancy 0.986. Source: [EVALUATION_REPORT §4.1](../../evaluation/EVALUATION_REPORT.md). Status: Verified. Conditions: single judge (Meta `muse-spark-1.3`), one run; sanity controls (fabricated, off-topic, irrelevant, contradictory) all scored 0.0 as expected.
- **Added a code-checked evaluation dataset.** 45 goldens, 66 evidence quotes each verified as exact transcript substrings. Source: [EVALUATION_REPORT §3](../../evaluation/EVALUATION_REPORT.md), [validate.py](../../evaluation/dataset/validate.py). Status: Implemented, Verified. Caveat: human review pending.
- **Shipped read-only MCP server on Cloudflare Workers (4 tools).** Source: [mcp-server/src](../../mcp-server/src), [docs/mcp-cloudflare](../mcp-cloudflare/). Status: Implemented, separate deploy. Hosted use: Not measured.

## 2. Architecture decisions

- **Replaced a dense-only retriever with hybrid retrieval: pgvector top 10 + in-memory BM25 top 10, fused by Reciprocal Rank Fusion (constant 60), reranked to 4 by a small ONNX cross-encoder.** Evidence: [backend/core/retrieval.py](../../backend/core/retrieval.py), [backend/core/reranker.py](../../backend/core/reranker.py), [EVALUATION_REPORT §2](../../evaluation/EVALUATION_REPORT.md). Status: Implemented. Honest note: on the 22-chunk test source, dense alone scored as well or better (recall@4 1.000 vs 0.977), so the evaluation does not prove hybrid beats dense; see Retrieval below.
- **Routed LLM calls through a free-tier fallback chain with per-route cooldowns and budget caps, and gated paid routes off by default.** Evidence: [llm_gateway.py](../../backend/core/llm_gateway.py), [provider_budget.py](../../backend/core/provider_budget.py) (paid cap $0.01 per job, $0.05 per day). Status: Implemented. Measured $0 provider cost for generation and embedding in the evaluation run ([EVALUATION_REPORT §5.2](../../evaluation/EVALUATION_REPORT.md)).
- **Chose Postgres-enforced quotas and job slots over Redis or a worker queue.** Evidence: [usage_limits.py](../../backend/usage_limits.py) (25 MiB upload; 1 job per IP per day; 5 jobs per day globally; 2 chats per IP per minute). Status: Implemented. Alternatives rejected: UPGRADE_IMPLEMENTATION_PLAN.md (removed; read with `git show dfa7e60:UPGRADE_IMPLEMENTATION_PLAN.md`).
- **Kept job processing as an in-process background task, with no checkpointing.** A crashed worker leaves its slot held until an operator runs `python -m backend.recover`. Evidence: [remaining-issues.md](../engineering-audit/remaining-issues.md), [ROADMAP_STATUS recovery section](../ROADMAP_STATUS.md). Status: Implemented, known limitation.

## 3. Performance

- **Cut peak container memory from 465.2 MiB to 425.0 MiB under a 512 MiB / 0.1 CPU limit; the original image failed the project's memory gate and the fixed image passed.** Evidence: [performance-and-optimization.md, Audit 2](../engineering-audit/performance-and-optimization.md). Status: Verified. Conditions: n=1 per image, Linux arm64, 120 s synthetic clip, mocked providers. Changes: removed two heavy imports, lazy-loaded `yt_dlp`.
- **Cut app startup from 22.8 s to 12.9 s at 0.1 CPU, and first-job title stage from 58.6 s to 10.6 s** (a model-library import had been charged against a 60 s deadline). Same source and conditions. First-job total went 78.4 s to 86.6 s, so the end-to-end first job did not improve; the source calls it noisy. Status: Verified.
- **Fixed an earlier out-of-memory failure on long uploads by replacing in-memory audio decoding with one streaming ffmpeg pass.** Evidence: [README.md line 247](../../README.md) (before and after memory numbers: Not measured in a tracked source). Status: Implemented.
- **Measured warm end-to-end chat latency on the evaluation talk: p50 2,085 ms, p95 5,128 ms (n=40), with generation over 99% of the time.** Retrieval stages: dense 5 ms, BM25 1 ms, rerank 8 ms (p50). Source: [EVALUATION_REPORT §6](../../evaluation/EVALUATION_REPORT.md), [usage_measurement.json](../usage_measurement.json). Status: Verified. Conditions: local run, free provider routes, query-embedding latency excluded.
- **Measured one 21-second clip analysis at 6,187 ms to result in the production image (512 MiB),** with stage times: ffmpeg 128, transcription 1,731, title 874, summary 647, findings 1,772, embed 743 ms. Source: [usage_measurement.json](../usage_measurement.json). Status: Verified, n=1. A separate local check recorded 8.1 s for another 21 s run ([LOCAL_RUN_CHECK.md](../LOCAL_RUN_CHECK.md)); these are two runs, not one result.

## 4. Cost

- **Zero provider spend per analysis on the free routes.** Evidence: `cost_usd.provider_calls: 0` in [usage_measurement.json](../usage_measurement.json); $0 generation and embeddings over 57 attempts in [EVALUATION_REPORT §5.2](../../evaluation/EVALUATION_REPORT.md). Status: Verified. Conditions: free-tier limits apply; hosted account limits are Not verified ([ROADMAP_STATUS gate 2](../ROADMAP_STATUS.md)).
- **Tracked the evaluation judge's real spend: $5.6087 for the reported run (1,284 calls) and $9.192293 across all runs in the ledger.** Source: [EVALUATION_REPORT §5.1](../../evaluation/EVALUATION_REPORT.md), `evaluation/reports/judge_ledger.json` (local, git-ignored; v1 total also in [EVALUATION_REPORT §5.1](../../evaluation/EVALUATION_REPORT.md), v2 total $3.58 in [v2 README](../../future-improvements/v2-rag-pipeline/README.md)). Status: Verified. The evaluation was not free; the app is.
- **Found that the app reserves about 3,440 input and 1,024 output tokens per chat while providers reported about 830 and 150.** Source: [EVALUATION_REPORT §5.2, §8.6](../../evaluation/EVALUATION_REPORT.md). Status: Verified finding; the fix is Planned (a v2 change, parked).

## 5. Reliability

- **Added Postgres-backed admission control: 8 concurrent submissions led to 1 admitted.** Source: [UPGRADE_VALIDATION.md](../UPGRADE_VALIDATION.md). Status: Verified (2026-11-05, local).
- **Ran two engineering audits: 44 findings in the second, 38 fixed, each fix with a regression test.** Source: [engineering-audit/README.md](../engineering-audit/README.md). Status: Verified. Audit scanners reported 0 known dependency vulnerabilities ([security-audit.md](../engineering-audit/security-audit.md)).
- **Found and fixed a cold-start failure:** a model route was disabled for the whole job after one timeout, and a first-call import exceeded its deadline. Source: [engineering-audit/README.md](../engineering-audit/README.md). Status: Verified locally; hosted behaviour Not measured.
- **Evaluation reliability finding:** 2 of 45 questions returned HTTP 503 because every model output was rejected by the citation validator (14 of 57 outputs rejected; 0 fabricated). Source: [EVALUATION_REPORT §7](../../evaluation/EVALUATION_REPORT.md). Status: Verified; fix exists only in the parked v2 patch.

## 6. Retrieval

- **recall@4 0.977 and MRR 0.892 for the production hybrid + rerank configuration (n=37).** Dense only: 1.000 / 0.946; BM25 only: 0.892 / 0.867; RRF without rerank: 0.964 / 0.928. Source: [metrics.json `ir`](../../evaluation/reports/metrics.json), [EVALUATION_REPORT §4.3](../../evaluation/EVALUATION_REPORT.md). Status: Verified. Conditions: 22-chunk corpus, so numbers are optimistic (chance recall@4 about 0.18).
- **Reranker on a weak first stage: recall@4 from 0.897 to 0.974, 95% CI [+0.026, +0.141] (BM25 only, n=39, offline).** Source: [experiment_comparison.md](../../evaluation/reports/experiment_comparison.md). Status: Verified.
- **Candidate-pool recall has two figures in tracked sources:** 0.949 / 0.923 / 0.949 (dense@10 / BM25@10 / fused@12) in the report, 1.000 / 0.973 / 1.000 in the comparison file. Denominators are not stated in the latter; quote the source you link and do not pick one silently. Status: Verified, discrepancy open.
- **Judged retrieval with DeepEval:** Contextual Recall 0.938 and Precision 0.924 on the final 4 chunks; Contextual Relevancy 0.237, which is structural for 500-character chunks (see [evaluation-strategy §7](evaluation-strategy.md)). Source: [EVALUATION_REPORT §4.1](../../evaluation/EVALUATION_REPORT.md). Status: Verified.

## 7. Experiments

- **Browser-side audio extraction (ffmpeg.wasm): worked on 3 synthetic clips, saved about 3% of bytes, needs a 32,232,419-byte GPL-2.0-or-later core. Rejected.** Timing matched native (for example 10 min clip: 1,025 ms vs 1,039 ms). Source: [BROWSER_MEDIA_EXPERIMENT.md](../BROWSER_MEDIA_EXPERIMENT.md). Status: Experimental, rejected. Upload-time or bandwidth benefit: Not measured.
- **Local BGE-small embeddings: recall@4 1.000 dense, 0.917 after RRF, 0.833 after rerank on 12 synthetic questions; kept offline.** Source: [BENCHMARK_NOTES.md](../BENCHMARK_NOTES.md). Status: Experimental, not hosted.
- **v2 RAG pipeline A/B: HTTP 503s 5 to 0 and behaviour accuracy 0.839 to 1.000, but Answer Relevancy 0.981 to 0.941 and e2e p95 4,519 to 6,289 ms (latency gate failed).** Source: [v2 README](../../future-improvements/v2-rag-pipeline/README.md), [comparison report](../../future-improvements/v2-rag-pipeline/reports/comparison_v1-pinned_vs_v2-iter1.md). Status: Experimental, parked. Conditions: 31 paired questions (latency n=24), interim, incomplete.
- **Offline chunking what-if:** sentence-packed chunks raised MRR 0.885 to 0.938 with 8% less context but covered slightly less evidence (0.957 vs 0.974); 20 of 21 current boundaries cut mid-word or mid-sentence. Source: [EVALUATION_REPORT §8.1](../../evaluation/EVALUATION_REPORT.md). Status: Verified offline; not shipped. Goldens were written against current chunks, which biases this.

## 8. Trade-offs

See section 10 for how to phrase them. Items: free tier over paid models (more failovers, slower tail); hybrid retrieval kept despite no gain on one small source; polling instead of streaming ([Not implemented](../../web/src/App.jsx), 3 s then 5 s with backoff); manual recovery instead of auto-recovery; browser preprocessing rejected.

## 9. Pending validation: do not claim yet

| Claim someone might want | Why not | How to measure |
|---|---|---|
| Hosted (Render) latency or memory | Only local container runs exist | Run the 512 MiB gate on the hosted service and record it |
| Native AMD64 gate on the current head | Local runs are arm64; CI artifacts are not in the repo | Check the CI run for the head commit ([ROADMAP_STATUS gate 1](../ROADMAP_STATUS.md)) |
| Real users, usage counts, uptime | No analytics sink; telemetry is log-only | Add an external metric sink first |
| Accuracy on other videos, languages or noisy audio | One English talk with human captions | Multi-source dataset (see [evaluation-strategy §10](evaluation-strategy.md)) |
| Speech-to-text quality | Not evaluated; captions stood in | WER on labelled audio |
| Bandwidth or upload-time savings from browser compression | Upload time not measured; bytes saved about 3% on synthetic files only | Measure upload with real media on real networks |
| Improvement over the original app | No baseline was ever measured for it | Cannot be recovered retroactively; start tracking from now |
| Live-provider behaviour and free-tier limits per account | Not verified ([ROADMAP_STATUS gate 2](../ROADMAP_STATUS.md)) | One live smoke run once authorised |
| v2 pipeline in production | Parked; latency gate failed | Re-run the A/B on one pinned generator |
| Human-reviewed answer quality | Goldens pending review | Review the 45 goldens |

## 10. How to talk about trade-offs

- **v2 parked for latency.** "v2 fixed the failures it targeted: 503s went from 5 to 0 on 31 paired questions. But p95 latency rose from 4.5 s to 6.3 s and failed my own gate, and the comparison was incomplete. I parked it with the patch and the reports in the repo rather than ship something I had not finished measuring."
- **Browser compression rejected.** "It worked and matched native speed, but saved about 3% of bytes on synthetic files, needs a 32 MB GPL-licensed wasm core, and I could not test low-power devices. No measured benefit, so I did not add it."
- **Manual recovery instead of automatic.** "If a worker dies, the single processing slot stays held until an operator runs the recovery command. I declined automatic recovery on startup because during a Render deploy the old and new instances can overlap, and releasing the slot could run two workers at once. It is a known limitation, documented."
- **Hybrid retrieval despite a flat result.** "On a 22-chunk talk, dense alone scored as well. I kept hybrid because BM25 protects exact names and numbers that this small set under-tests, and I said so: one short source cannot justify removing it."
- **Free tier over paid.** "Cost per analysis is $0, but free models reject more outputs and fail over more, which shows up as a slower tail: p50 1,944 ms on first attempt vs 4,729 ms when failover was needed."

## Sources

- [evaluation/EVALUATION_REPORT.md](../../evaluation/EVALUATION_REPORT.md)
- [evaluation/reports/metrics.json](../../evaluation/reports/metrics.json)
- [evaluation/reports/experiment_comparison.md](../../evaluation/reports/experiment_comparison.md)
- `evaluation/reports/judge_ledger.json` (local, git-ignored; v1 total also in [EVALUATION_REPORT §5.1](../../evaluation/EVALUATION_REPORT.md), v2 total $3.58 in [v2 README](../../future-improvements/v2-rag-pipeline/README.md))
- [evaluation/dataset/validate.py](../../evaluation/dataset/validate.py)
- [docs/engineering-audit/performance-and-optimization.md](../engineering-audit/performance-and-optimization.md)
- [docs/engineering-audit/README.md](../engineering-audit/README.md)
- [docs/engineering-audit/remaining-issues.md](../engineering-audit/remaining-issues.md)
- [docs/engineering-audit/security-audit.md](../engineering-audit/security-audit.md)
- [docs/usage_measurement.json](../usage_measurement.json)
- [docs/LOCAL_RUN_CHECK.md](../LOCAL_RUN_CHECK.md)
- [docs/BROWSER_MEDIA_EXPERIMENT.md](../BROWSER_MEDIA_EXPERIMENT.md)
- [docs/BENCHMARK_NOTES.md](../BENCHMARK_NOTES.md)
- [docs/UPGRADE_VALIDATION.md](../UPGRADE_VALIDATION.md)
- [docs/ROADMAP_STATUS.md](../ROADMAP_STATUS.md)
- [future-improvements/v2-rag-pipeline/README.md](../../future-improvements/v2-rag-pipeline/README.md)
- [README.md](../../README.md)
- [backend/usage_limits.py](../../backend/usage_limits.py), [backend/core/provider_budget.py](../../backend/core/provider_budget.py), [backend/core/retrieval.py](../../backend/core/retrieval.py)
