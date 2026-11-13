# Optimization and experiments

Purpose: one record per optimization idea in this repo, with the hypothesis, what was changed, what was actually measured, and the decision taken. Experiments that were never run are labelled "Not run" and are not given results.

## Status legend

| Tag | Meaning |
| --- | --- |
| Implemented | Present in code on branch `eval/deepeval-framework` (code cited). |
| Verified | Implemented and covered by a tracked measurement, test or run log. |
| Experimental | Built and measured in isolation; not part of the shipped app. |
| Planned | Described in a tracked doc as future work; no code. |
| Not implemented | No code. |
| Not run | No experiment exists. No result is stated. |

Evidence classes used in the tables: **Measured** (a number in a tracked artifact, with its conditions), **Estimated** (derived arithmetically from measured numbers; the derivation is shown), **Expected** (the source predicts it; not measured), **Hypothesis** (reasoning only).

Two global caveats:

- The original application (commit `29eddf7`, 13 Jul 2026) had **no latency or quality baseline measured**. "Baseline" below means the previous design or variant, never a recorded number, unless a number is quoted.
- Most latency numbers come from free-tier providers with one run (n=1) or a small n. They are conditions of that day, not capacity claims.

---

## 1. Streaming ffmpeg pass (Render OOM fix, `0ea372e`)

| Field | Entry |
| --- | --- |
| Hypothesis | Decoding the whole upload with `pydub` held raw PCM in RAM twice (`convert_to_wav` then `chunk_audio`), which is what pushed long uploads past Render's 512 MB limit. One streaming ffmpeg pass should keep memory flat regardless of length. (Commit message, 16 Jul 2026.) |
| Baseline | `pydub` convert + chunk. Symptom recorded in the commit message: "Ran out of memory (used over 512MB)" on long uploads. No peak-memory number was recorded for the old path. |
| Change | One ffmpeg pass `-vn -ac 1 -ar 16000 -f segment` (300 s WAV pieces), `-t 600` cap, protocol and format whitelists, temp cleanup. Upload streamed to disk in bounded reads with a clean 413 over the cap. [`audio_processor.py:125-211`](../../backend/utils/audio_processor.py), [`jobs.py:115-121`](../../backend/jobs.py) |
| Experiment | No before/after measurement of the pydub path exists in the repo. The new path was later exercised inside the 512 MiB / 0.1 CPU workload gate (see [benchmarking](benchmarking-and-performance.md)). Those gates test the post-fix pipeline only. |
| Result | Symptom fixed per the commit message (Implemented). Post-fix gate: cgroup peak 425.0 MiB, 0 OOM events, 0 bytes of temp files left, on a 120 s clip (audit 2, [perf doc](../engineering-audit/performance-and-optimization.md)). **Pre-fix peak memory: Not measured.** |
| Trade-off | Chunk files are written to disk. Analysis is capped at the first 600 s of media (`MAX_MEDIA_SECONDS`, `audio_processor.py:40-44`). The cap on upload size has since been tightened: the commit message says a default of 200 MB, current code caps at 25 MiB (`usage_limits.py:44`). |
| Decision | **Keep.** |

How to measure the missing baseline (offline, no provider calls): build the image at `0ea372e^` and at `0ea372e`, run each with `docker run --memory 512m --memory-swap 512m`, feed the same long local media file to the conversion function only, and read `/sys/fs/cgroup/memory.peak` inside the container afterwards.

---

## 2. Browser-side audio extraction (ffmpeg.wasm)

| Field | Entry |
| --- | --- |
| Hypothesis | Extracting mono 16 kHz audio in the browser would shrink the upload and offload CPU from the free backend. |
| Baseline | The app uploads the raw file (`web/src/api.js:76-83`). Native ffmpeg on the server. |
| Change | None in the app. Isolated prototype: [`scripts/browser-media-experiment/index.html`](../../scripts/browser-media-experiment/index.html), single-thread `@ffmpeg/ffmpeg` 0.12.15 + `@ffmpeg/core` 0.12.10 in a Web Worker. |
| Experiment | Three synthetic files (30 s, 2 min, 10 min; 160x90 solid-colour H.264 + sine-wave AAC), one run each, arm64 Mac, Playwright Chrome 157, native FFmpeg 9.0.2. [BROWSER_MEDIA_EXPERIMENT](../BROWSER_MEDIA_EXPERIMENT.md) |
| Result (measured) | Worker extraction 158 / 229 / 1,025 ms vs native MP3 extraction 125 / 231 / 1,039 ms for 30 s / 2 min / 10 min. Bytes: 186,356 to 180,940; 744,681 to 720,940; 3,722,557 to 3,600,868. Core wasm is 32,232,419 bytes. |
| Result (estimated) | Byte saving is about 2.9%, 3.2% and 3.3% (my arithmetic from the three pairs above). The roadmap quotes "about 3%". |
| Not measured | Real network upload time, backend round trip, peak browser memory, energy, low-power devices, other browsers, ASR quality, cancellation. The source states these were not tested. |
| Trade-off | The single-thread core is GPL-2.0-or-later (compliance review needed before shipping). A 32 MB download for a ~3% saving on synthetic, unusually compressible media. |
| Decision | **Reject (Experimental, rejected).** The doc's own decision is "do not enable browser preprocessing". Nothing in the app claims bandwidth reduction. |

---

## 3. Parallel transcription

| Field | Entry |
| --- | --- |
| Hypothesis | Sending chunks to the speech-to-text provider concurrently would cut transcription wall time. |
| Baseline | Chunks are sent one after another: a plain loop in [`transcribe_segments`](../../backend/core/transcriber.py) (`:278-303`). Free routes (Groq, Gemini, Sarvam) follow the fallback chain at `:226-252`. |
| Change | **Free routes: none.** Parallelism exists only on the paid Meta route: 30 s pieces, 10 at a time (`META_PIECE_SECONDS = 30`, `META_PARALLEL = 10`, `transcriber.py:19-21`, thread pool at `:151`). That route is opt-in and gated (see [cost doc](cost-and-resource-optimization.md)). |
| Experiment | **Free routes: Not run.** For Meta, the only evidence is a code comment: ASR "took 131 s for one 5-minute file; 30 s pieces, 10 at a time, took 31 s" (`transcriber.py:19`). One observation, no raw artifact in the repo. |
| Result | Meta: 131 s to 31 s on one 5-minute file, as stated in a code comment (not reproducible from tracked artifacts). Free routes: no result. |
| Trade-off | Free routes carry per-profile `rpm`, `rpd`, `audio_seconds_hour` and `audio_seconds_day` caps enforced in Postgres (`audio_budget.py:86-112`). No source states why free routes are sequential; that parallelism would burn those caps faster is **Hypothesis**. Sarvam additionally rejects audio over 30 s, so it is sliced to 25 s pieces (`transcriber.py:13`). |
| Decision | **Not run** for free routes. **Keep** the Meta parallel path as implemented. |

Related, measured in a code comment only: uploading Groq chunks as lossless FLAC instead of WAV is "~45% smaller, measured 11.4 s vs 19.7 s per 5-minute Groq request" (`transcriber.py:66`, with WAV fallback). Status: Implemented. Decision: **Keep**. Single observation, no tracked artifact.

How to run the missing free-route experiment (needs approval, uses provider quota): with one approved Groq profile, time `transcribe_segments` for the same 10-minute local clip sequentially and with a thread pool of 2, from a script outside the app, and compare `audio_attempts` rows and 429 counts.

---

## 4. Local embeddings (BGE-small)

| Field | Entry |
| --- | --- |
| Hypothesis | Quantized BGE-small ONNX could replace hosted embeddings and remove one remote dependency. |
| Baseline | Hosted embedding routes (Gemini 768-d, Cloudflare Qwen3 1,024-d, OpenRouter and NVIDIA Nemotron 2,048-d). The original app used `mistral-embed`. |
| Change | None in the app. Offline script [`scripts/benchmark_local_embeddings.py`](../../scripts/benchmark_local_embeddings.py). |
| Experiment | One arm64 Mac, exact cosine search over 16 synthetic English passages and 12 hand-labelled questions, same BM25/RRF/FlashRank code. [BENCHMARK_NOTES](../BENCHMARK_NOTES.md) (`:40-52`) |
| Result (measured) | Recall@4 / MRR: dense 1.000 / 0.896; +BM25 +RRF 0.917 / 0.736; +TinyBERT 0.833 / 0.750. Model + tokenizer 67,176,520 bytes. Load 111 ms, passages embedded in 174 ms, median per question 12.5 ms (embed + cosine), 0.28 ms (BM25 + fusion), 13.5 ms (rerank). Process peak RSS 326.3 MiB. |
| Trade-off | The model would have to live in the same 512 MiB container as the app, which already peaks at 425.0 MiB cgroup in the audit 2 gate. A joint hosting benchmark was not run. The fixture is small, synthetic and English only. |
| Decision | **Keep offline; do not host.** The source: keep it offline until representative evaluation and a joint hosting benchmark justify adding it. |

---

## 5. Hybrid retrieval (dense + BM25)

| Field | Entry |
| --- | --- |
| Hypothesis | BM25 protects exact-term queries (names, numbers, acronyms) that dense retrieval can miss. |
| Baseline | Original app: dense-only k=4 on Mistral embeddings (git `29eddf7`); never measured. Comparison below is against the current pipeline's dense-only variant on Gemini embeddings, not the original. |
| Change | Dense pgvector k=10 (job-filtered) + in-memory `rank_bm25` BM25Okapi k=10 rebuilt per query; Postgres full-text search was replaced by BM25. [`retrieval.py`](../../backend/core/retrieval.py) |
| Experiment | Replay of the 45-golden run against the NASA COP26 talk (22 chunks), gold chunk ids, k=4, n=37 paired requests, paired bootstrap 95% CI. [EVALUATION_REPORT §4.3](../../evaluation/EVALUATION_REPORT.md), [experiment_comparison.md](../../evaluation/reports/experiment_comparison.md) |
| Result (measured) | recall@4 / MRR / nDCG@4: dense 1.000 / 0.946 / 0.951; BM25 only 0.892 / 0.867 / 0.826; hybrid RRF 0.964 / 0.928 / 0.909. BM25 alone is significantly worse than production (-0.086, CI [-0.144, -0.032]). Dense alone vs production: +0.023, CI [0.000, +0.059], not significant. |
| Trade-off | On this one short corpus dense alone matched or beat the hybrid. The report's own warning: this small set under-tests exact-term queries, so it cannot show the benefit BM25 is kept for. BM25 costs about 1 ms p50 per question. |
| Decision | **Keep.** The "BM25 helps exact terms" rationale remains a **Hypothesis**; re-evaluate on a multi-source dataset (report §8.10). |

Candidate-pool recall appears with two different values in tracked sources: the report text (`EVALUATION_REPORT.md:196`) says dense@10 0.949, BM25@10 0.923, fused@12 0.949, while `experiment_comparison.md:20-22` says 1.000, 0.973, 1.000. The report says its figures are against the full gold set; the JSON-derived file is over the 37 captured requests. The two are consistent with denominators of 39 and 37 (37/39 = 0.949; 36/39 = 0.923). That reconciliation is my arithmetic, not stated in either source.

---

## 6. Reciprocal Rank Fusion (RRF)

| Field | Entry |
| --- | --- |
| Hypothesis | Rank-based fusion merges dense and BM25 lists without having to calibrate their incompatible scores. |
| Baseline | Each list alone (section 5). |
| Change | `score = sum 1/(60 + rank)` over both lists, de-duplicated by chunk id, top 12 (`reciprocal_rank_fusion`, `retrieval.py:44-57`). |
| Experiment | Same replay as section 5. Variant `hybrid_rrf` (rerank off). |
| Result (measured) | recall@4 0.964, MRR 0.928, nDCG@4 0.909. Versus production (hybrid + rerank) recall: -0.014, CI [-0.041, 0.000], not significant. RRF stage latency p50 0 ms, p95 0 ms (n=42, [report §6](../../evaluation/EVALUATION_REPORT.md)). |
| Trade-off | Fusion lost to dense-only on this corpus (0.964 vs 1.000 recall@4). The constant 60 was not tuned. |
| Decision | **Keep.** Tuning the constant: **Not run.** |

---

## 7. Cross-encoder reranking (FlashRank TinyBERT)

| Field | Entry |
| --- | --- |
| Hypothesis | A local cross-encoder on the top 12 fused candidates improves the final top 4. |
| Baseline | RRF top 4 without rerank; also, offline, BM25 only. |
| Change | `ms-marco-TinyBERT-L-2-v2` via FlashRank (ONNX, max length 512, hash-verified assets, process singleton), top 4. [`reranker.py`](../../backend/core/reranker.py) |
| Experiment | Online replay (n=37) plus an offline BM25 variant, with paired bootstrap CIs. Latency from app telemetry (n=42). |
| Result (measured) | Hybrid + rerank vs hybrid without: recall@4 0.977 vs 0.964 (not significant), MRR 0.892 vs 0.928, nDCG@4 0.897 vs 0.909. Offline, BM25 only vs BM25 + rerank: recall@4 0.897 to 0.974, +0.077, CI [+0.026, +0.141]. Rerank latency p50 8 ms, p95 10 ms. FlashRank load 0.098 s cold, inference about 0.085 s per 12-pair stress call, process RSS 274,120,704 bytes ([BENCHMARK_NOTES](../BENCHMARK_NOTES.md), macOS arm64, single run). |
| Failure cases | H-005 and M-005 dropped from judge-recall 1.0 to 0.0 after rerank. E-001, E-003, N-006 had an off-topic chunk ranked first. Pre-rerank Contextual Precision 0.877 vs 0.924 after (different judged sample sizes, 31 vs 32). |
| Trade-off | Helps a weak first stage clearly; on a strong dense list it lowers MRR. Reranker failure stops generation (retrieval contract, [ROADMAP_STATUS](../ROADMAP_STATUS.md)). Adds memory to a 512 MiB container. |
| Decision | **Keep; Investigate.** The report says not to remove it on one short source. Open candidates (report §8.8): top-k 5, blending cross-encoder with RRF score, a larger cross-encoder if it fits memory. All **Not run.** |

---

## 8. Timestamp-aware chunking and the sentence-packed what-if

| Field | Entry |
| --- | --- |
| Hypothesis (timestamps) | Chunks that carry start and end times let citations link to a position in the video. |
| Baseline | Original app: `RecursiveCharacterTextSplitter` 500/50, no timestamps (git `29eddf7`). No before/after retrieval measurement. |
| Change | 500-character window, 450 stride (50 overlap), short tail folded in; each chunk takes the minimum start and maximum end of the transcript segments it covers; a precision label; length-preserving PII mask. [`chunks.py:7-31`](../../backend/core/chunks.py) |
| Result (measured) | Chunk timestamps span a median 47.6 s, maximum 68.7 s; 20 of 21 chunk boundaries cut mid-word or mid-sentence (report §8.1). Citation validity 56/56. |
| Decision | **Keep (Implemented, Verified).** |

What-if on chunk shape (offline, no network, BM25 + TinyBERT, quote coverage@4 over 39 questions; method in [report §9](../../evaluation/EVALUATION_REPORT.md), scratch script not committed):

| Chunking | Chunks | Top-4 context (chars) | Quote coverage@4 | Fully covered | MRR |
| --- | --- | --- | --- | --- | --- |
| Current 500/450 window | 22 | 2,000 | 0.974 | 37/39 | 0.885 |
| Sentence-packed ~500, 1-sentence overlap | 28 | 1,836 | 0.957 | 34/39 | 0.938 |
| Cue-packed ~500, 1-cue overlap | 28 | 1,814 | 0.949 | 33/39 | 0.938 |
| Sentence-packed ~350 | 51 | 1,188 | 0.855 | 29/39 | 0.872 |
| Sentence-packed ~250 | 78 | 805 | 0.784 | 26/39 | 0.833 |

| Field | Entry |
| --- | --- |
| Result | Smaller chunks lose multi-part evidence (coverage falls to 0.855 and 0.784). Sentence-packing at ~500 ranks better (MRR 0.885 to 0.938) with about 8% less context, at slightly lower coverage. |
| Trade-off | The goldens' quotes were chosen to fit the current chunks, which biases toward the current scheme (report's own warning). Dense retrieval was not covered. Gemini's free daily cap was exhausted. |
| Decision | **Reject** smaller chunks. **Keep** current chunking; sentence-packed is **Investigate**: written into the parked v2 patch (item 9 in the [v2 README](../../future-improvements/v2-rag-pipeline/README.md)), not shipped. |

---

## 9. LLM routing and fallbacks

| Field | Entry |
| --- | --- |
| Hypothesis | Several free-tier models behind an ordered fallback keep answers available when one route is rate-limited or returns unusable output. |
| Baseline | Original app: one Mistral model (`mistral-small-latest`). Later removed because the API needs billing ([HYBRID_IMPLEMENTATION](../HYBRID_IMPLEMENTATION.md):85). |
| Change | LiteLLM single-model call per attempt with the application owning the loop (retries and fallbacks set to 0), 60 s generation deadline, per-route timeout `min(12 s, remaining / routes_left)`, 429 cooldown from `Retry-After`, 30 s transient cooldown, validator failure moves to the next route. [`llm_gateway.py`](../../backend/core/llm_gateway.py) |
| Experiment | Evaluation run, 45 questions, 57 provider attempts, four free routes, one run. [Report §6-7](../../evaluation/EVALUATION_REPORT.md) |

Measured, generation latency per route (ms):

| Route | p50 | p95 | Responses | Accepted |
| --- | --- | --- | --- | --- |
| Groq gpt-oss-20b | 1,004 | 1,828 | 8 | 5 |
| Gemini 2.5 Flash | 1,858 | 2,796 | 17 | 15 |
| NVIDIA Nemotron 30B-A3B | 2,159 | 3,213 | 23 | 16 |
| OpenRouter Nemotron free | 2,688 | 3,099 | 9 | 7 |

| Field | Entry |
| --- | --- |
| Result (measured) | First-attempt answers p50 1,944 ms, p95 3,667 ms (n=38). Answers that needed failover p50 4,729 ms, max 9,474 ms (n=5), about 2.4x slower (4,729 / 1,944). 14 of 57 responses were rejected by the citation validator: 5 real text crossing a chunk boundary, 4 spacing-only differences, 3 stitched quotes, 2 empty-answer abstentions, 0 fabricated. Two questions ended in HTTP 503 (all routes rejected). Mean 1.27 attempts per question. |
| Trade-off | Rejections drive the latency tail and the two 503s. Fallback is needed, but acceptance differs by route (Groq 5/8, Gemini 15/17). Mixed generators in one run mean quality is only comparable with a pinned route (report §10). |
| Decision | **Keep.** Route ordering by speed and acceptance: **Investigate** (report §8.7, config only, not run). Rejected earlier: LiteLLM `Router` per call as an optimization ("cost is negligible next to the network call", [perf doc](../engineering-audit/performance-and-optimization.md)). Fixed in audit 2: one timeout no longer disables a route for the rest of the job. |

---

## 10. Embedding failover chain

| Field | Entry |
| --- | --- |
| Hypothesis | Ordering free embedding providers lets indexing survive one provider being down or capped. |
| Baseline | A fixed route order forced OpenRouter first, so Gemini could never be primary; the OpenRouter route always failed because `:free` replies are labelled `private/openrouter/<model>` and the exact-name check rejected them ([LOCAL_RUN_CHECK](../LOCAL_RUN_CHECK.md)). |
| Change | `EMBEDDING_ROUTES_JSON` order is the failover order; the whole corpus is embedded on one route before the index is written; chat pins the persisted route and dimension. Gemini 768-d, Cloudflare Qwen3 1,024-d, OpenRouter and NVIDIA Nemotron 2,048-d; batch 100 for Gemini, else 16. Nemotron routes are disabled on Render. [`embedding_routes.py`](../../backend/core/embedding_routes.py), [`vector_store.py:90-137`](../../backend/core/vector_store.py) |
| Experiment | One probe: Cloudflare `@cf/qwen/qwen3-embedding-0.6b` through the app's own request and parse code returned HTTP 200 with 1,024 dimensions for documents and queries (13 Nov, local). |
| Result | Verified for the probe only. **Failover latency and the cost of a mid-index route switch: Not measured.** Embedding latency on the primary route: 743 ms for 1 chunk (21 s clip, [usage_measurement.json](../usage_measurement.json)); 2,195 ms for 22 chunks (eval index). |
| Trade-off | Switching routes means re-embedding the whole job (vectors from different models are not mixable), so a late failure repeats work. |
| Decision | **Keep.** To measure failover: with owner-approved keys, put a deliberately failing route first in `EMBEDDING_ROUTES_JSON` and read `elapsed_ms` and `status` from `provider_attempts` for the job. |

---

## 11. Streaming responses (SSE / token streaming)

| Field | Entry |
| --- | --- |
| Hypothesis | Streaming the answer would improve perceived chat latency. |
| Baseline | Chat is one POST returning a complete JSON answer; `'stream': False` in the gateway (`llm_gateway.py:229`); no `StreamingResponse`. Job progress is polled: 3 s for the first 30 s then 5 s, doubling on errors up to 20 s, pauses when the tab is hidden (`web/src/App.jsx`). |
| Change | None. |
| Experiment | **Not run.** |
| Result | None. Context only: generation is more than 99% of per-question time in the evaluation (report §1), so time to first token is where streaming would act. That is an observation about the baseline, not a measured gain. |
| Trade-off | **Hypothesis:** answers are validated as whole JSON (`chunk_id` + exact quote) before being returned, so token streaming would conflict with citation validation. |
| Decision | **Not run (Not implemented).** |

---

## 12. Job recovery and checkpointing

| Field | Entry |
| --- | --- |
| Hypothesis | A restart or OOM-kill mid-job should not leave the single global processing slot held forever. |
| Baseline | `BackgroundTasks` job, no durable queue. A Render restart loses the job; it stays `running` and holds the slot. |
| Change | **Manual, fenced recovery** (Implemented): `python -m backend.recover inspect` and `recover processing --all-workers-stopped`. Requires 30 minutes since reservation, marks the job `interrupted`, releases the reservation in one transaction. ([ROADMAP_STATUS](../ROADMAP_STATUS.md)) **Checkpointing / auto-resume: Not implemented** (would need durable input and provider idempotency). |
| Experiment | Startup auto-recovery was considered and **declined**: during a Render deploy old and new instances can overlap, and releasing the slot could run two workers ([remaining-issues](../engineering-audit/remaining-issues.md)). Phase 1 validation: 8 concurrent submissions admitted 1 ([UPGRADE_VALIDATION](../UPGRADE_VALIDATION.md)). |
| Result | Recovery behaviour is covered by tests; **time-to-recover on a hosted instance: Not measured.** |
| Trade-off | An operator must act. Related open gap: the job budget is checked only after transcription, so a dense 10-minute clip can fail after paid-quota transcription. |
| Decision | **Keep** manual recovery. Checkpointing: **Not run.** Auto-recovery: **Reject.** |

---

## 13. Caching

| Field | Entry |
| --- | --- |
| Hypothesis | Caching repeated work would cut provider calls. |
| Baseline | Only an SQLAlchemy engine cache and a reranker process singleton. Responses are `no-store`. |
| Change | None in production. The evaluation harness caches query embeddings, but that is an evaluation-only deviation (report §3). |
| Experiment | **Not run.** There is no measurement of how often questions or embeddings repeat. |
| Result | None. |
| Trade-off | **Hypothesis:** with 1 job per IP per day and 3 chats per job per day, repeat hit rates are probably low. Unmeasured. |
| Decision | **Not run (Not implemented).** |

---

## 14. Import cost and startup (audit 2)

| Field | Entry |
| --- | --- |
| Hypothesis | Heavy imports raise memory, slow startup and, at 0.1 CPU, eat the 60 s generation deadline. |
| Baseline | Image built from `6ac48a2`. |
| Change | Removed `langchain.agents` (PII detectors replaced by local regexes) and `langchain_community` (BM25Okapi called directly); lazy `yt_dlp`; BM25 tokenizes each document once instead of three times per query; reranker tokenizer built once per process; one pooled PGVector engine; no reduce call for a single summary partial; LiteLLM imported in the pre-admission preflight; a transient failure no longer disables a route. |
| Experiment | CI workload gate recipe on both images, Linux arm64 Colima, 512 MiB, 0 swap, 0.1 CPU, n=1, 120 s synthetic clip, mocked providers. Import cost: macOS arm64, `import backend.api`, n=5 mean. [perf doc](../engineering-audit/performance-and-optimization.md) |

| Metric | Original | Fixed |
| --- | --- | --- |
| Gate result | FAIL ("exceeded the release memory threshold") | PASS |
| cgroup peak memory | 465.2 MiB | 425.0 MiB |
| Python peak RSS | 408.3 MiB | 374.6 MiB |
| App import + startup | 22.8 s | 12.9 s |
| First job, title stage | 58.6 s (1.4 s under the 60 s deadline) | 10.6 s |
| First job total | 78.4 s | 86.6 s |
| Warm job / warm chat | 11.6 s / 2.5 s | 11.0 s / 1.6 s |
| Generation calls for 3 jobs | 15 | 12 |
| Image size | 1.75 GB | 1.69 GB |
| `import backend.api` peak RSS / time (macOS) | 130.3 MiB / 604 ms | 112.3 MiB / 484 ms |

| Field | Entry |
| --- | --- |
| Result | Measured as above. First-job total got slower (78.4 to 86.6 s) because LiteLLM's import moved earlier; the source calls it noisy at 0.1 CPU with n=1. BM25 ranking parity: 0 of 500 randomized pairs differ. |
| Trade-off | One run each; the first-job total regression is not explained further. Isolated import deltas overlap, so the whole-app saving is less than their sum (langchain pii +47.9 MiB / 258 ms; `yt_dlp` +26.0 MiB / 73 ms). |
| Decision | **Keep.** Considered and rejected for no measured benefit: psycopg connection pool (stale-connection risk on autosuspending Neon), `Router` per call, de-duplicating `sanitize_text` on the chat path. |

---

## 15. v2 RAG pipeline A/B

| Field | Entry |
| --- | --- |
| Hypothesis | Fixing the validator and chunking issues found in v1 (tolerant quote matching, re-attribution, empty abstention, sentence chunking, a new prompt, an output cap of 768, token settlement) would remove the 503s and the failover tail. |
| Baseline | v1, pinned to the same generator (NVIDIA Nemotron 3.5 Lightning) and embedding model, over 31 paired questions. |
| Change | `v2.patch`, 29 files, never merged. [v2 README](../../future-improvements/v2-rag-pipeline/README.md) |
| Experiment | Pre-registered gate, paired comparison ([comparison report](../../future-improvements/v2-rag-pipeline/reports/comparison_v1-pinned_vs_v2-iter1.md)). Offline replay of v1's 14 rejected outputs through the v2 validator. |
| Result (measured) | HTTP 503: 5 to 0. Behaviour accuracy 0.839 to 1.000. Faithfulness 1.000 to 1.000. Answer Relevancy 0.981 to 0.941 (CI [-0.136, +0.038], includes 0). Quote coverage@4 1.000 to 0.974. End-to-end p95 4,519 ms to 6,289 ms: **latency gate FAIL**. Replay: 9 accepted, 2 valid abstentions, 3 still rejected (all correctly). Judge spend $3.58. |
| Trade-off | v2 answers were about 45% longer (output-token median 106 to 154), and the run shared the NVIDIA account with two concurrent runs. |
| Decision | **Reject for now (parked).** The report's verdict: v2 is not shown to be better. The concision fix was never re-measured, and the A/B is incomplete (last 14 v1 questions and the v2 repeat judge run were not done). |

---

## Decision summary

| # | Experiment | Status | Decision |
| --- | --- | --- | --- |
| 1 | Streaming ffmpeg (OOM fix) | Implemented | Keep (pre-fix memory Not measured) |
| 2 | Browser audio extraction | Experimental | Reject |
| 3 | Parallel transcription | Free routes: not implemented. Meta: Implemented | Free: Not run. Meta: Keep |
| 3b | FLAC upload to Groq | Implemented | Keep (comment-level evidence) |
| 4 | Local embeddings (BGE-small) | Experimental | Keep offline, do not host |
| 5 | Hybrid retrieval | Implemented, Verified | Keep (benefit of BM25 is a hypothesis) |
| 6 | RRF | Implemented, Verified | Keep; constant tuning Not run |
| 7 | Reranking | Implemented, Verified | Keep; top-k 5 / blend / larger model Investigate |
| 8 | Timestamp-aware chunking | Implemented, Verified | Keep |
| 8b | Smaller chunks | Experimental (offline) | Reject |
| 8c | Sentence-packed chunks | Experimental (offline, in v2 patch) | Investigate |
| 9 | LLM routing + fallback | Implemented, Verified | Keep; route order Investigate |
| 10 | Embedding failover chain | Implemented | Keep; failover latency Not measured |
| 11 | Streaming responses | Not implemented | Not run |
| 12 | Manual recovery | Implemented | Keep |
| 12b | Checkpointing / auto-resume | Not implemented | Not run; auto-recovery Reject |
| 13 | Caching | Not implemented | Not run |
| 14 | Import-cost / startup cuts | Implemented, Verified | Keep |
| 15 | v2 RAG pipeline | Experimental, parked | Reject for now |

## Sources

- [`docs/engineering-audit/performance-and-optimization.md`](../engineering-audit/performance-and-optimization.md)
- [`docs/BROWSER_MEDIA_EXPERIMENT.md`](../BROWSER_MEDIA_EXPERIMENT.md)
- [`docs/BENCHMARK_NOTES.md`](../BENCHMARK_NOTES.md)
- [`docs/LOCAL_RUN_CHECK.md`](../LOCAL_RUN_CHECK.md)
- [`docs/usage_measurement.json`](../usage_measurement.json)
- [`docs/ROADMAP_STATUS.md`](../ROADMAP_STATUS.md), [`docs/UPGRADE_VALIDATION.md`](../UPGRADE_VALIDATION.md), [`docs/HYBRID_IMPLEMENTATION.md`](../HYBRID_IMPLEMENTATION.md)
- [`docs/engineering-audit/remaining-issues.md`](../engineering-audit/remaining-issues.md)
- [`evaluation/EVALUATION_REPORT.md`](../../evaluation/EVALUATION_REPORT.md), [`evaluation/reports/experiment_comparison.md`](../../evaluation/reports/experiment_comparison.md)
- [`future-improvements/v2-rag-pipeline/README.md`](../../future-improvements/v2-rag-pipeline/README.md) and its [comparison report](../../future-improvements/v2-rag-pipeline/reports/comparison_v1-pinned_vs_v2-iter1.md)
- Code: [`backend/core/transcriber.py`](../../backend/core/transcriber.py), [`backend/core/retrieval.py`](../../backend/core/retrieval.py), [`backend/core/reranker.py`](../../backend/core/reranker.py), [`backend/core/chunks.py`](../../backend/core/chunks.py), [`backend/core/llm_gateway.py`](../../backend/core/llm_gateway.py), [`backend/core/embedding_routes.py`](../../backend/core/embedding_routes.py), [`backend/core/vector_store.py`](../../backend/core/vector_store.py), [`backend/core/audio_budget.py`](../../backend/core/audio_budget.py), [`backend/utils/audio_processor.py`](../../backend/utils/audio_processor.py), [`backend/usage_limits.py`](../../backend/usage_limits.py)
- Git: commit `0ea372e` message (16 Jul 2026), `29eddf7` (first commit)
