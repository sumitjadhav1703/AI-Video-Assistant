# Performance and optimization

## Audit 2 — 13 November 2026

Only measured numbers are reported. "n" is the number of runs; single runs at 0.1 CPU are noisy.

### 512 MiB / 0.1 CPU workload gate (CI recipe)

**Setup:**
- Linux arm64 (Colima), with the same 120 s synthetic video and the same disposable pgvector for both images. Run once each (n=1).
- Ran `python -m scripts.benchmark_recruiter_demo … --linux-gate` with `--memory 512m --memory-swap 512m --cpus 0.1`.
- The original image was built from `6ac48a2`; the fixed image from this branch.

| Metric | Original | Fixed |
| --- | --- | --- |
| Gate result | **FAIL**: "exceeded the release memory threshold" | **PASS** |
| cgroup peak memory | 465.2 MiB | **425.0 MiB** (−40.2) |
| Python peak RSS | 408.3 MiB | **374.6 MiB** (−33.7) |
| OOM events | 0 | 0 |
| App import + startup | 22.8 s | **12.9 s** |
| First job title stage | 58.6 s (1.4 s under the 60 s deadline) | **10.6 s** |
| First job total | 78.4 s | 86.6 s (LiteLLM import moved earlier; noisy at 0.1 CPU) |
| Warm job / warm chat | 11.6 s / 2.5 s | 11.0 s / 1.6 s |
| Generation calls for 3 jobs | 15 | **12** |
| Leftover temp files | 0 bytes | 0 bytes |
| Image size | 1.75 GB | **1.69 GB** |

On the first fixed-image run, before the B1 fix, title generation took 60.2 s and the job failed. The original image passed that stage by only 1.4 s. The previous audit's AMD64 failure "at title generation after 101.5 s" is the same defect.

### Import cost on macOS arm64 (`import backend.api`, n=5 mean)

| | Original | Fixed |
| --- | --- | --- |
| Peak RSS | 130.3 MiB | **112.3 MiB** |
| Import time | 604 ms | **484 ms** |

Isolated import deltas measured: `langchain.agents.middleware.pii` +47.9 MiB / 258 ms, and `yt_dlp` +26.0 MiB / 73 ms. Part of that is shared with other modules, so the whole-app saving is smaller than the sum.

### Changes made

- **Imports:** removed `langchain.agents` (PII detectors replaced by local regexes) and `langchain_community` (`BM25Okapi` is now called directly). Ranking parity: 0 of 500 randomized query/corpus pairs differ.
- **Lazy `yt_dlp`:** imported only on the CLI download path.
- **BM25:** each document is tokenized once instead of three times per query.
- **Reranker:** the token-counting tokenizer is built once per process, not on every chat.
- **PGVector:** one pooled engine replaces a new engine per call. No `CREATE EXTENSION` per chat.
- **Fewer model calls:** no reduce call for a single summary partial (−1 call per short job).
- **Gateway:** a transient failure no longer disables a route for the job, which avoids needless fallback calls and failures.

### Considered and not changed (no measured benefit)

- **psycopg connection pool:** each DB call opens a TLS connection to Neon. A pool to a free Neon endpoint that autosuspends adds stale-connection risk, and the latency gain could not be measured without Neon.
- **LiteLLM `Router` per call:** the cost is negligible next to the network call.
- **Repeated `sanitize_text` on the chat path:** about microseconds per chunk, and it is defense in depth.

---

# Previous audit (11–12 November 2026)

## Before and after

| Check | Before | After |
| --- | ---: | ---: |
| Job deletion median | 7.95 ms | 3.36 ms |
| Job deletion p95 | 8.33 ms | 3.58 ms |
| PostgreSQL connections per delete | 3 | 1 |
| Extra status and result requests on completed-session resume | 2 | 0 |
| Document scroll width at a 320 px viewport | 577 px | 320 px |

Deletion used 40 sequential synthetic jobs per variant on the same loopback PostgreSQL installation. Each job had one chunk and one vector row. Fixture creation was outside the measured interval. The browser results came from the same navigation and viewport before and after the UI fixes. These numbers describe the local fixtures.

## Final native workload

The final macOS arm64 run processed three 120-second synthetic clips of 1,147,142 bytes each. It used FFmpeg, real PostgreSQL/pgvector, FlashRank, and intercepted provider HTTP. A chat overlapped the second upload.

| Metric | Measured |
| --- | ---: |
| App import and startup | 1.789 s |
| Cold upload and chat | 4.218 s / 0.093 s |
| Overlapping upload and chat | 0.381 s / 0.376 s |
| Warm upload and chat | 0.336 s / 0.081 s |
| Peak Python RSS | 429,932,544 bytes (410.02 MiB) |
| Python CPU and child-process CPU | 6.076 s / 0.813 s |
| Sampled peak temporary file bytes | 4,987,220 |
| Temporary file bytes remaining | 0 |
| Intercepted STT, embedding and generation requests | 3 / 6 / 15 |
| Audio reserved and text attempts | 360,000 ms / 21 |

The earlier native run peaked at 407.45 MiB process RSS. Native RSS excludes other processes and differs from Linux cgroup usage. Temp bytes are sampled at stage milestones. The Linux gate and exact commands are in [Offline workload check](../RECRUITER_DEMO.md#offline-workload-check).


## Linux cgroup v2 release test

The local Docker image built from `e1c906f`. Colima ran Docker Engine 29.5.2 in a Linux VM. Each workload used real FFmpeg, PostgreSQL with pgvector, BM25, RRF, FlashRank, and intercepted provider HTTP. The backend was limited to 512 MiB with zero swap and 0.1 CPU. PostgreSQL ran in a separate cgroup.

| Metric | Native Linux ARM64 | Linux AMD64 under Rosetta, one CPU |
| --- | ---: | ---: |
| Docker build and non-root startup | PASS | PASS |
| 450 MiB release threshold | Met | Exceeded |
| cgroup peak memory | 380.83 MiB | 472.28 MiB |
| Python peak RSS | 404.88 MiB | 460.07 MiB |
| cgroup CPU | 3.552 s | 7.356 s |
| OOM / OOM kill events | 0 / 0 | 0 / 0 |
| Cold upload / chat | 19.468 s / 0.695 s | 4.009 s / 0.173 s |
| Overlapping upload / chat | 5.081 s / 4.915 s | 1.063 s / 1.090 s |
| Warm upload / chat | 2.724 s / 0.603 s | 1.003 s / 0.105 s |
| Sampled peak / remaining temporary bytes | 4,987,220 / 0 | 4,987,220 / 0 |

Each successful run completed three 120-second jobs, three grounded chats, and all deletes. The fixture intercepted 3 transcription, 6 embedding, and 15 generation requests. Timing from a local VM is sensitive to host load and does not predict hosted provider latency.

At 0.1 CPU, the AMD64 Rosetta workload reached transcription and then returned HTTP 500 after 101.5 seconds in title generation. This is consistent with exhausting the gateway's 60-second generation deadline during the cold call. The one-CPU diagnostic preserved the memory and swap limits and used a fresh database. An earlier QEMU run was stopped during the cold title stage.
