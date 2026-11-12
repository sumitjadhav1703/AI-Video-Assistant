# Performance and optimization

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
