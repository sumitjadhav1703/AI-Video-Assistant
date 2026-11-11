# Recruiter demo

The hosted sample is a static Vite experience. It includes a synthetic clip, prepared findings, two cited answers and an abstention example. Opening the sample requires only the frontend assets. The live mode is checked when the visitor opens live analysis.

## Live modes

| `DEMO_LIVE_MODE` | Behavior |
| --- | --- |
| `sample` | The default. Live submissions and chat are closed. |
| `invited` | Visitors enter the private `DEMO_INVITE_CODE` before submitting an English clip. |
| `public` | Visitors submit English clips under the same upload, concurrency, and provider limits. |

Configure distinct random values for `DEMO_INVITE_CODE`, `JOB_TOKEN_SECRET`, and `RATE_LIMIT_SECRET` on the backend. Keep the signing secret stable across restarts. Rotating it invalidates existing session tokens. The browser stores the current job ID and its 48-hour token in same-tab session storage. Refresh resumes status checks. Explicit deletion removes the job and its index. The scheduled cleanup sweep makes terminal records eligible after 24 hours and skips active jobs. Actual deletion depends on the sweep running successfully.

Use only synthetic or permitted non-personal clips. The demo allows up to 10 MiB and 120 seconds per upload. It starts with one upload per client and five globally per UTC day, two chat requests per client per minute, three per job per day, and 15 globally per day. Admit at most one processing job and one chat at a time. Retain the [operator recovery procedure](ROADMAP_STATUS.md#recovery-after-an-interrupted-process) for interrupted work.

## Offline workload check

Use a fresh disposable PostgreSQL database named `recruiter_demo_test` on IPv4 loopback with pgvector available. Prepare the pinned FlashRank assets and supply a synthetic video. The script refuses to use a database with an existing jobs table. Its isolated configuration uses dummy credentials and intercepts provider HTTP. The two runs use actual FFmpeg, pgvector, BM25, RRF, FlashRank, and the provider accounting path. The second run overlaps indexing with chat.

```sh
ffmpeg -nostdin -f lavfi -i color=blue:size=640x360:rate=15 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 -t 120 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac /tmp/recruiter-benchmark.mp4
TEST_DATABASE_URL=postgresql://TEST_USER@127.0.0.1:TEST_PORT/recruiter_demo_test \
  python -m scripts.benchmark_recruiter_demo /tmp/recruiter-benchmark.mp4
```

A macOS test database may use the local pgvector test fixture via `PGVECTOR_TEST_SQL_PATH` and `TESTPGVECTORLIB`. For the release gate, run the same command with `--linux-gate` inside a fresh cgroup v2 container limited to `--memory 512m --memory-swap 512m --cpus 0.1`. Use a disposable pgvector database sharing the container network namespace so the database is reachable via loopback and its memory is measured separately. The gate checks the container's full peak memory below 450 MiB and requires both completed jobs and a validated overlapping chat answer. The script records stage durations, reserved usage, and peak memory. Mocked responses cannot measure live provider latency or quota enforcement.

## Local verification

- All 166 Python tests passed with disposable PostgreSQL and pgvector. Five frontend tests and the Vite production build passed.
- The browser opened the silent sample, sought to a cited timestamp, and made zero backend requests. Mocked live browser checks covered invited and public uploads, same-tab refresh, quota feedback, cited chat, deletion failure and success, and interrupted jobs.
- The macOS workload processed two 120-second clips and completed a chat during the second job. The first job took 2.24 seconds, the overlapping job and chat each took 0.30 seconds, and Python peak RSS was 381.4 MiB. These are local mocked-provider measurements. The Linux cgroup measurement is pending.
- After the provider failover update, the mocked workload again completed two jobs and an overlapping chat. Peak Python RSS was 380.7 MiB on macOS. The local Singapore Blueprint passed Render's published schema validation.

## Release order

1. After push and deployment approval, create an empty Neon Free project in AWS Singapore (`aws-ap-southeast-1`). Deploy the approved commit to the new `ai-video-assistant-api-sg` Render Free service in Singapore with manual deploys, `sample` mode, and inference off. Set its `DATABASE_URL` to the new project and verify schema initialization and pgvector.
2. Deploy the static `web/` frontend on Vercel Hobby. Set its `VITE_BACKEND_URL` to the new Render URL and add the exact Vercel origin to `FRONTEND_ORIGIN` on Render. Verify the sample opens and seeks citations with the backend blocked. Set the cleanup workflow's `BACKEND_URL` and `ADMIN_TOKEN` to the new service and verify its target. Keep the old services until the replacement passes cutover checks if free capacity permits. The owner can then retire the old projects. The replacement starts with an empty database.
3. Before hosted live access, verify Vercel Hobby, Render Free bandwidth and build overage protection, Neon Free, and model entitlements for each configured route. Complete the Linux workload gate. After approval, enable `invited` with the [verified free generation routes](HYBRID_IMPLEMENTATION.md#provider-and-release-gates), one embedding profile, and one English STT profile. Run a bounded synthetic smoke test and verify Render proxy identity and quota exhaustion behavior before opening `public`. [Render Free](https://render.com/docs/free) · [Vercel Hobby](https://vercel.com/docs/plans/hobby) · [Neon plans](https://neon.com/docs/introduction/plans)
4. Return to `invited` to restrict live submissions. Use `sample` and disable provider calls when a resource or billing gate fails. Keep capability checks enabled on any live rollback. Keep the separate Cloudflare MCP deployment outside this cutover.
