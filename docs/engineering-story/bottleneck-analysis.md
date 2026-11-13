# Bottleneck analysis

Purpose: for each of 12 bottlenecks in the original application, what it did, why, what evidence exists, what was changed, and what is still open.

**Status legend.** Implemented / Verified (tested, evidence cited) / Planned / Experimental / Not implemented. "Original" means the first git commit `29eddf7` (2026-07-13) unless noted. The pre-git local CLI is not in the history; no latency or quality baseline for any early version was recorded, so before/after timings are only given where a source has both. Overview: [README.md](README.md).

---

## 1. Large video uploads

- **Original behaviour.** `backend/api.py` at `29eddf7` has no size check (searching it for size, MB and read limits finds none). Commit `0ea372e` added a streamed copy in 1 MiB reads with a default cap of 200 MB (`MAX_UPLOAD_MB` default "200").
- **Root cause.** Uploads land on Render's ephemeral disk and then feed decoding; a large file multiplies memory and time cost on a 512 MiB / free CPU instance.
- **Evidence.** `git show 0ea372e -- backend/api.py`. Current: cap of 25 MiB, empty and oversized files rejected before they consume the daily allowance, copy loop in 1 MiB pieces ([`backend/api.py`](../../backend/api.py):38,434-454); media trimmed to the first 600 s by `ffmpeg -t` ([`audio_processor.py`](../../backend/utils/audio_processor.py):39-42,146-170).
- **User impact.** Clips over 25 MiB are refused; longer clips are analysed only for the first 10 minutes.
- **Solution.** Hard caps before any provider spend. Browser-side extraction was tried to shrink uploads and rejected: about 3% fewer bytes on three synthetic clips, 32 MB wasm download, GPL review needed ([`BROWSER_MEDIA_EXPERIMENT.md`](../BROWSER_MEDIA_EXPERIMENT.md):3-17).
- **Trade-offs.** Lower caps protect free quotas but limit the demo. Actual upload time on a real connection and the compressed size of real recordings: **Not measured**. To measure: upload a licensed 20 MiB clip over throttled network and read the `upload_copy` metric (`bytes`, `elapsed_ms`) from the logs.
- **Status.** Cap Implemented; browser preprocessing Experimental, rejected.

## 2. Backend audio extraction

- **Original behaviour.** pydub: `AudioSegment.from_file` to decode the whole file, export a WAV, then `AudioSegment.from_wav` to cut 5-minute chunks (`git show 29eddf7:backend/utils/audio_processor.py`, lines 49-71).
- **Root cause.** Decoded PCM held in RAM twice (the project's own wording in the README added by `0ea372e`, line 247: it "exceeded Render's 512MB limit on long uploads").
- **Evidence.** Fix in `0ea372e`; current code runs `ffprobe` (30 s timeout, protocol and format whitelist) then one `ffmpeg` pass: `-t 600 -vn -ac 1 -ar 16000 -f segment -segment_time 300` ([`audio_processor.py`](../../backend/utils/audio_processor.py):125-181). The ffmpeg stage took 128 ms on a 21 s clip ([`docs/usage_measurement.json`](../usage_measurement.json)). The pre-fix peak memory was **not recorded**.
- **User impact.** Before: long uploads could be killed with an out-of-memory error. After: memory flat with respect to length per the code comment and the cgroup gate (bottleneck 12).
- **Solution.** Streaming ffmpeg; temp files cleaned in `finally` ([`jobs.py`](../../backend/jobs.py):115-121).
- **Trade-offs.** Depends on the ffmpeg binary (hence Docker); decoding of untrusted media is a security surface, mitigated by whitelists and a non-root user.
- **Status.** Implemented. Verified for 120 s synthetic clips in the 512 MiB gate; very long real media not measured.

## 3. Sequential transcription

- **Original behaviour.** `transcribe_all` loops over chunks one at a time (`git show 29eddf7:backend/core/transcriber.py`, lines 105-122). Sarvam path also slices 25 s pieces and sends them in order.
- **Root cause.** One pass, one provider, simple loop; STT is rate-limited, so more concurrency is not free.
- **Evidence.** Still sequential today: loop at [`transcriber.py`](../../backend/core/transcriber.py):278-303; Sarvam pieces at :255-275. The only parallel path is the paid Meta route (30 s pieces, 10 workers, lines 20-21,151). A code comment says Meta took 131 s for one 5-minute file sequentially and 31 s with pieces 10 at a time; this is a code comment, not a reproducible benchmark. Measured on a 21 s clip: STT 1,731 ms (one chunk, 5 segments, [`usage_measurement.json`](../usage_measurement.json)).
- **User impact.** With the 600 s cap there are at most two 300 s chunks (computed), so serial cost is bounded. STT time for a 10-minute clip on free routes: **Not measured**. To measure: run `scripts/benchmark_recruiter_demo.py` with a real 10-minute clip and live free routes (needs authorization) and read `stt_chunk` stage times.
- **Solution.** Cap length rather than parallelise; fallback chain for failures. Parallel STT stays off the free path.
- **Trade-offs.** Parallel free-tier calls would burn per-minute audio limits faster.
- **Status.** Sequential: Implemented. Parallel STT: Not implemented (except paid Meta route, off by default).

## 4. STT API rate limits

- **Original behaviour.** Groq (English) or Sarvam (Hinglish) with no quota tracking; no application-level limits at all (plan, [`UPGRADE_IMPLEMENTATION_PLAN.md`](../../UPGRADE_IMPLEMENTATION_PLAN.md):19-26 area, "no quotas").
- **Root cause.** Free tiers have per-minute, per-hour and per-day audio ceilings; Sarvam's allowance is a finite signup credit (plan).
- **Evidence.** [`backend/core/audio_budget.py`](../../backend/core/audio_budget.py):42-112 reserves each attempt in a Postgres `audio_attempts` table under a lock, checking requests per minute and day and audio seconds per hour and day for each provider/model. `STT_PROFILES_JSON` lists up to 8 profiles; every non-Meta profile must carry `verified_free`. Transcription tries profiles in order, skips routes that return 401/403/404 for the rest of the job ([`transcriber.py`](../../backend/core/transcriber.py):226-252). Groq uploads are FLAC, about 45% smaller, per a code comment that also claims 11.4 s versus 19.7 s per 5-minute request (single code comment, not reproduced here). Published Groq free limits cited by the review: 20 RPM, 2,000 RPD, 7,200 audio seconds/hour, 28,800/day ([`architecture-review.md`](../reviews/architecture-review.md):67), public docs, not verified for this account.
- **User impact.** When a limit is hit the job fails with a retry message instead of a provider error; one job per IP per day.
- **Solution.** Local ledger plus fallback chain.
- **Trade-offs.** Limits are attested by the operator; live free-tier behaviour is unverified (tests use mocked HTTP).
- **Status.** Implemented; Verified offline only.

## 5. Embedding generation time

- **Original behaviour.** `mistral-embed` through PGVector `from_documents` for the whole transcript (`git show 29eddf7:backend/core/vector_store.py`).
- **Root cause.** One remote call path, no failover, billing needed (Mistral); chunk count grows with transcript length.
- **Evidence.** Now: ordered routes (Gemini 768 dims, Cloudflare Qwen 1,024, OpenRouter and NVIDIA Nemotron 2,048), batch 100 for Gemini else 16, whole corpus embedded in one space before any write ([`embedding_routes.py`](../../backend/core/embedding_routes.py):13-18,62-63; [`vector_store.py`](../../backend/core/vector_store.py):90-122). Measured: indexing 22 chunks 2,195 ms; one chunk 743 ms; batched embedding of 45 queries 2,303 ms (about 51 ms each); single-query latency in the short-clip run 850 and 765 ms ([`EVALUATION_REPORT.md`](../../evaluation/EVALUATION_REPORT.md) section 6, [`usage_measurement.json`](../usage_measurement.json)). OpenRouter and NVIDIA routes are disabled on Render by code (NVIDIA trial terms).
- **User impact.** Embedding is a small share of the 6,187 ms to result on a 21 s clip. Each chat question also pays one embedding call.
- **Solution.** Failover, batching, pinned route per job so queries use the same space. A local BGE-small ONNX run exists as an offline experiment (model 67,176,520 bytes, peak RSS 326.3 MiB) and was not adopted for hosting ([`BENCHMARK_NOTES.md`](../BENCHMARK_NOTES.md):52).
- **Trade-offs.** A failover re-embeds the whole job. Old jobs depend on their original route staying enabled.
- **Status.** Implemented, Verified locally; Cloudflare route probed with a 1,024-dimension reply ([`LOCAL_RUN_CHECK.md`](../LOCAL_RUN_CHECK.md)). Local embeddings: Experimental.

## 6. Vector retrieval limitations

- **Original behaviour.** Dense similarity only, `k = 4`, 500/50 character splitter, no timestamps, no job-isolation checks beyond one collection per job (`git show 29eddf7:backend/core/rag_engine.py`, `vector_store.py`).
- **Root cause.** Dense recall depends on the embedding model; chunks carried no time provenance so answers could not cite positions.
- **Evidence.** Now dense returns 10 candidates filtered by `job_id`, with isolation checks on every hit ([`retrieval.py`](../../backend/core/retrieval.py):69-77). Chunks carry `start_ms`, `end_ms` and a precision label ([`chunks.py`](../../backend/core/chunks.py)). On the one evaluation talk, dense-only was the strongest variant: recall@4 1.000, MRR 0.946, n=37 ([`EVALUATION_REPORT.md`](../../evaluation/EVALUATION_REPORT.md) section 4.3).
- **User impact.** The measured dense weakness was not demonstrated; the evaluation shows misses on multi-passage questions where evidence spans 2-3 chunks and only 4 fit. A what-if: current chunking MRR 0.885 / coverage 0.974 versus sentence-packed 0.938 / 0.957; 20 of 21 chunk boundaries fall mid-word or mid-sentence.
- **Solution.** Wider candidate pool, job isolation, timestamps. Sentence-aware chunking sits in the parked v2 pipeline.
- **Trade-offs.** Smaller chunks reduced coverage in the what-if. Evidence is one source.
- **Status.** Implemented, Verified on one source. Retrieval quality on varied real audio: **Not measured**.

## 7. Lack of keyword retrieval

- **Original behaviour.** None. Exact names, numbers and acronyms depended on the embedding.
- **Root cause.** Dense-only design.
- **Evidence.** BM25 added in [`retrieval.py`](../../backend/core/retrieval.py):26-39, fused with dense by RRF. Parity with the library implementation: 0 of 500 randomized pairs differ. BM25 p50 1 ms. Results, n=37: BM25 alone recall@4 0.892 (worse than production by 0.086, CI [-0.144, -0.032]); hybrid RRF 0.964 versus dense 1.000, not significant.
- **User impact.** Benefit for exact-term questions is expected but under-tested: the evaluation says the small set under-tests names, numbers and acronyms. Treat as hypothesis.
- **Solution.** In-memory BM25 over the job's chunks instead of Postgres full-text (plan note, reason undocumented; see [architecture-and-decisions.md](architecture-and-decisions.md) section 5).
- **Trade-offs.** Per-query rebuild is fine for tens of chunks, not for large corpora.
- **Status.** Implemented; improvement **not demonstrated** on current data.

## 8. Missing reranking

- **Original behaviour.** None; top 4 dense hits went straight to the LLM.
- **Root cause.** No second-stage scorer.
- **Evidence.** Mandatory FlashRank TinyBERT over up to 12 fused candidates, top 4 out ([`reranker.py`](../../backend/core/reranker.py):72-93). Rerank p50 8 ms, p95 10 ms (n=42); RSS 274,120,704 B in one benchmark run. Offline weak-list test: recall@4 0.897 to 0.974, CI [+0.026, +0.141]. On the hybrid list it dropped needed passages for 2 questions (H-005, M-005) and lowered MRR from 0.928 to 0.892.
- **User impact.** Mixed. Reranker failure returns 503 rather than silently skipping.
- **Solution.** Keep it; future options are blending scores or a larger model if memory allows (evaluation 8.8).
- **Trade-offs.** One more local model inside a 512 MiB budget; assets must be checksum-verified at build.
- **Status.** Implemented; value on real data **not shown**.

## 9. Job interruption on Render restart

- **Original behaviour.** `BackgroundTasks` with `db.set_step`; rows survive a restart, the running work does not (`29eddf7` `jobs.py`; [`architecture-review.md`](../reviews/architecture-review.md):33).
- **Root cause.** In-process tasks on a free instance that can restart or be OOM-killed at any time; uploaded files live on ephemeral disk.
- **Evidence.** A killed worker leaves the job `running` and the one global processing slot held. Recovery is a manual command: wait 30 minutes, stop all workers, run `python -m backend.recover recover processing --all-workers-stopped` ([`recover.py`](../../backend/recover.py), [`db.py`](../../backend/db.py):12,381-406). Startup auto-recovery was declined because overlapping Render deploys could run two workers ([`remaining-issues.md`](../engineering-audit/remaining-issues.md):12).
- **User impact.** After a crash the user must re-upload, and every other visitor is blocked until an operator clears the slot. Frequency of restarts on the hosted instance: **Not measured** (no hosted checks yet).
- **Solution.** Fail closed with an operator tool. Checkpointing was suggested by the review but not built.
- **Trade-offs.** Safe against double-processing; poor availability.
- **Status.** Manual recovery Implemented; checkpointing and auto-resume Not implemented.

## 10. Frontend polling overhead

- **Original behaviour.** Streamlit slept 3 s between reads (`frontend/app.py:491` at `29eddf7`) and `GET /jobs/{id}` called `get_job`, which ran `SELECT *` (`db.py:114`), pulling the whole transcript and summaries from Neon on every poll ([`architecture-review.md`](../reviews/architecture-review.md):49-53).
- **Root cause.** One query serving both status and result.
- **Evidence.** Now `GET /jobs/{id}` calls `get_job_status`, selecting `id, status, step, error` only ([`api.py`](../../backend/api.py):485-490, [`db.py`](../../backend/db.py):240-242). The React client polls every 3 s for 30 s then 5 s, doubles the delay on errors up to 20 s, honours `Retry-After`, stops after 5 minutes, and pauses when the tab is hidden ([`App.jsx`](../../web/src/App.jsx):13-17,99-190). Extra status and result requests when resuming a completed session fell from 2 to 0 ([`performance-and-optimization.md`](../engineering-audit/performance-and-optimization.md):61-69).
- **User impact.** Status lag of up to 5 s. Bytes saved per poll: **Not measured**; measure by comparing response and query sizes for a finished job before and after `get_job_status`.
- **Solution.** Narrow query plus backoff. SSE was not built (see decisions section 9).
- **Trade-offs.** Simple and stateless; not instant.
- **Status.** Polling fix Implemented; SSE Not implemented.

## 11. Missing or incomplete observability

- **Original behaviour.** `print` statements in the pipeline (for example `print(f"Transcribing chunk ...")` at `29eddf7`); question and answer text was logged in `rag_engine.py:67-69` per the review ([`architecture-review.md`](../reviews/architecture-review.md):53).
- **Root cause.** No telemetry design.
- **Evidence.** [`backend/core/telemetry.py`](../../backend/core/telemetry.py) emits `metric=... key=value` log lines and per-stage `duration` with status; values must not carry user content. Stages are wrapped in [`jobs.py`](../../backend/jobs.py):54-97. `/health` is static liveness and `/ready` checks the database ([`api.py`](../../backend/api.py):303-311). `GET /usage` and the `/usage` page show live allowance. Provider attempts are recorded in Postgres ledgers. There is no external metrics sink, alerting or tracing.
- **User impact.** Operators read logs; no dashboards. Success or error rates over time: **Not measured**.
- **Solution.** Privacy-safe log metrics and ledgers; external sink Not implemented. To close the gap: ship the log lines to a free log drain and chart `stage` durations.
- **Trade-offs.** Cheap and private, but no history beyond Render's log retention.
- **Status.** Implemented, log-only.

## 12. Memory and CPU limits

- **Original behaviour.** Render Free is 512 MiB. The pre-git stack used local whisper + torch + Chroma; the original deployment plan removed whisper/torch from the backend requirements (`git show 29eddf7:DEPLOYMENT_PLAN.md`, Task 2). A code comment estimated that stack at "~2GB against Render's 512MB free tier" (`git show 29eddf7:backend/requirements.txt`, line 3); it was never measured. The pydub path then exceeded memory on long uploads (bottleneck 2). No memory baseline was recorded for `29eddf7`.
- **Root cause.** Heavy imports, in-process model (TinyBERT), decode memory, and 0.1 CPU-class throttling at cold start.
- **Evidence.** Gate with 512 MiB, no swap, 0.1 CPU, Linux arm64 (Colima), 120 s synthetic clip, mocked providers, n=1 ([`performance-and-optimization.md`](../engineering-audit/performance-and-optimization.md):7-37):

| Metric | Original image | Fixed image |
|---|---|---|
| Gate | FAIL | PASS |
| cgroup peak | 465.2 MiB | 425.0 MiB |
| Python peak RSS | 408.3 MiB | 374.6 MiB |
| Startup | 22.8 s | 12.9 s |
| First job title stage | 58.6 s | 10.6 s |
| First job total | 78.4 s | 86.6 s (noisy) |
| Generation calls for 3 jobs | 15 | 12 |
| `import backend.api` RSS | 130.3 MiB | 112.3 MiB |

  Earlier runs: Linux ARM64 380.83 MiB; AMD64 under Rosetta 472.28 MiB, and at 0.1 CPU an HTTP 500 at title after 101.5 s. The 12 Nov ARM64 gate peaked at 365.96 MiB ([`RECRUITER_DEMO.md`](../RECRUITER_DEMO.md):83).
- **User impact.** Fixes the cold-start failure where LiteLLM's first import (about 55 s at 0.1 CPU) consumed the 60 s generation deadline.
- **Solution.** Removed `langchain.agents` (+47.9 MiB import) and `langchain_community`, lazy `yt_dlp` (+26.0 MiB), import LiteLLM before admission deadline, reranker tokenizer built once.
- **Trade-offs.** Single runs at 0.1 CPU are noisy (first job total got slower). Headroom under 512 MiB is about 87 MiB. Native AMD64 on the current head and real-provider RSS on Render: **Not measured**; CI runs the AMD64 gate per [`SAMPLE_DEPLOYMENT.md`](../SAMPLE_DEPLOYMENT.md):36.
- **Status.** Implemented; Verified on arm64 only.

---

## Summary

| # | Bottleneck | Applied solution | Evidence quality | Status |
|---|---|---|---|---|
| 1 | Large uploads | 25 MiB cap, 600 s trim | Code; upload time not measured | Implemented |
| 2 | Audio extraction | One streaming ffmpeg pass | Code, gate | Verified (arm64, synthetic) |
| 3 | Sequential STT | Length cap, fallback chain | Code; 10-min STT time not measured | Sequential kept; parallel Not implemented |
| 4 | STT rate limits | Postgres ledger, chain | Offline tests | Implemented |
| 5 | Embedding time | Failover, batches, pinned route | Measured on 22 chunks | Implemented |
| 6 | Dense-only retrieval | k=10, isolation, timestamps | One-source eval | Verified (one source) |
| 7 | No keyword search | In-memory BM25 | Parity test; gain not shown | Implemented |
| 8 | No reranking | TinyBERT | Mixed eval | Implemented; benefit not shown |
| 9 | Restart interrupts jobs | Manual fenced recovery | Docs and code | Manual only; auto Not implemented |
| 10 | Polling overhead | Narrow status query, backoff | Review + code | Implemented; SSE Not implemented |
| 11 | Observability | Log metrics, ledgers | Code | Implemented, log-only |
| 12 | Memory and CPU | Import cuts, streaming | Gate numbers, n=1 | Verified (arm64) |

## Sources

- Code: [`backend/api.py`](../../backend/api.py), [`jobs.py`](../../backend/jobs.py), [`db.py`](../../backend/db.py), [`recover.py`](../../backend/recover.py), [`core/transcriber.py`](../../backend/core/transcriber.py), [`core/audio_budget.py`](../../backend/core/audio_budget.py), [`core/embedding_routes.py`](../../backend/core/embedding_routes.py), [`core/vector_store.py`](../../backend/core/vector_store.py), [`core/retrieval.py`](../../backend/core/retrieval.py), [`core/reranker.py`](../../backend/core/reranker.py), [`core/telemetry.py`](../../backend/core/telemetry.py), [`utils/audio_processor.py`](../../backend/utils/audio_processor.py), [`web/src/App.jsx`](../../web/src/App.jsx)
- Docs: [`architecture-review.md`](../reviews/architecture-review.md), [`UPGRADE_IMPLEMENTATION_PLAN.md`](../../UPGRADE_IMPLEMENTATION_PLAN.md), [`performance-and-optimization.md`](../engineering-audit/performance-and-optimization.md), [`remaining-issues.md`](../engineering-audit/remaining-issues.md), [`BROWSER_MEDIA_EXPERIMENT.md`](../BROWSER_MEDIA_EXPERIMENT.md), [`BENCHMARK_NOTES.md`](../BENCHMARK_NOTES.md), [`usage_measurement.json`](../usage_measurement.json), [`LOCAL_RUN_CHECK.md`](../LOCAL_RUN_CHECK.md), [`RECRUITER_DEMO.md`](../RECRUITER_DEMO.md), [`EVALUATION_REPORT.md`](../../evaluation/EVALUATION_REPORT.md)
- Git (read-only): `git show 29eddf7:<path>` for `backend/api.py`, `backend/core/transcriber.py`, `backend/core/vector_store.py`, `backend/core/rag_engine.py`, `backend/utils/audio_processor.py`, `frontend/app.py`, `DEPLOYMENT_PLAN.md`; `git show 0ea372e`
