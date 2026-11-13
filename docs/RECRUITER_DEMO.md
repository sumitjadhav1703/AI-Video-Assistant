# Recruiter demo

The original Minutes workspace opens at `/` and checks live availability. The `/eval`, `/usage` and `/pipeline` pages explain the evaluation, usage limits and pipeline; `/eval` and `/pipeline` need only the frontend assets. The old static `/sample` demo was removed.

Live results show chat beside the summary and findings on desktop and above them on mobile. The full transcript is collapsed at the bottom. Use **New session** to delete the current job and start another.

## Demo videos for live analysis

**Try a demo video** on the home page loads a named recording into the upload form. The two bundled MP4s use original fictional scripts and synthetic speech generated locally with [CMU Flite](https://github.com/festvox/flite/tree/v2.2). The visitor clicks **Analyse** to start a job, subject to live-mode, invite, and quota checks. For a user-selected file, the form explains before submission that audio goes to a transcription provider and that clips must contain synthetic or public, non-personal material.

To add a clip from Google Drive, download the recording as the project maintainer. Verify that its license allows redistribution, record the source and required attribution, and use a non-personal English clip with audible speech. Encode its audio only (`ffmpeg -i input -t 600 -vn -ac 1 -ar 16000 -c:a libmp3lame -b:a 48k name.mp3`) and add the MP3 to `web/public/demo-clips/` and its display title and filename to the catalog in `web/src/components/Empty.jsx`. Vite publishes these assets with the frontend, so visitors load them from the Minutes site. [Google Drive download options](https://developers.google.com/workspace/drive/api/guides/manage-downloads)

## Live modes

| `DEMO_LIVE_MODE` | Behavior |
| --- | --- |
| `sample` | The default. Live submissions and chat are closed. |
| `invited` | Visitors enter the private `DEMO_INVITE_CODE` before submitting an English clip. |
| `public` | Visitors submit English clips under the same upload, concurrency, and provider limits. |

Configure distinct random values for `DEMO_INVITE_CODE`, `JOB_TOKEN_SECRET`, and `RATE_LIMIT_SECRET` on the backend. Keep the signing secret stable across restarts. Rotating it invalidates existing session tokens. The browser stores the current job ID and its 48-hour token in same-tab session storage. Refresh resumes status checks. Explicit deletion removes the job and its index. The scheduled cleanup sweep makes terminal records eligible after 24 hours and skips active jobs. Actual deletion depends on the sweep running successfully.

Use only synthetic or permitted non-personal clips. The demo allows up to 25 MiB per upload and analyses the first 10 minutes. It starts with one upload per client and five globally per UTC day, two chat requests per client per minute, three per job per day, and 15 globally per day. Admit at most one processing job and one chat at a time. Retain the [operator recovery procedure](ROADMAP_STATUS.md#recovery-after-an-interrupted-process) for interrupted work.

## Local browser checks

Start Vite on `127.0.0.1:5173` with a local backend target. From the repository root, point `AVA_PLAYWRIGHT_MODULE` at a local Playwright `index.mjs`. Set `AVA_CHROMIUM_EXECUTABLE` to an installed Chromium or Chrome executable if Playwright's bundled browser is unavailable.

```sh
export AVA_FRONTEND_TEST_URL=http://127.0.0.1:5173
export AVA_BACKEND_TEST_URL=https://sample-fixture.invalid
node web/tests/live-session.browser.mjs
node web/tests/pages.browser.mjs
```

The live-session check supplies mock API responses. The pages check blocks backend requests and verifies `/eval`, `/usage` and `/pipeline`, and that `/sample` now serves the home page.

## Offline workload check

Use a fresh disposable PostgreSQL database named `recruiter_demo_test` on IPv4 loopback with pgvector available. Prepare the pinned FlashRank assets and supply a synthetic video. The script refuses to use a database with an existing jobs table. Its isolated configuration uses dummy credentials and intercepts provider HTTP. The workload uses actual FFmpeg, pgvector, BM25, RRF, FlashRank, and the provider accounting path. It runs a cold upload and chat, overlaps a second upload with chat, then repeats upload and chat on the warmed service.

```sh
ffmpeg -nostdin -f lavfi -i color=blue:size=640x360:rate=15 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 -t 120 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac /tmp/recruiter-benchmark.mp4
TEST_DATABASE_URL=postgresql://TEST_USER@127.0.0.1:TEST_PORT/recruiter_demo_test \
  python -m scripts.benchmark_recruiter_demo /tmp/recruiter-benchmark.mp4
```

A macOS test database may use the local pgvector test fixture via `PGVECTOR_TEST_SQL_PATH` and `TESTPGVECTORLIB`. For the release gate, use a Linux Docker engine with cgroup v2. The test database shares the backend's loopback network namespace and runs in its own cgroup. Start from the repository root with the synthetic clip above.

```sh
docker build -t ava-audit-backend .
docker run --rm -d --name ava-audit-db --network none \
  -e POSTGRES_USER=audit -e POSTGRES_DB=recruiter_demo_test \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  pgvector/pgvector:0.8.1-pg16 -c listen_addresses=127.0.0.1
docker exec ava-audit-db pg_isready -h 127.0.0.1 -U audit -d recruiter_demo_test
```

Once PostgreSQL accepts connections, run the workload and stop the disposable database afterward.

```sh
docker run --rm --network container:ava-audit-db --cgroupns private \
  --memory 512m --memory-swap 512m --cpus 0.1 \
  --mount "type=bind,source=$PWD/scripts,target=/app/scripts,readonly" \
  --mount type=bind,source=/tmp/recruiter-benchmark.mp4,target=/tmp/recruiter-benchmark.mp4,readonly \
  -e TEST_DATABASE_URL=postgresql://audit@127.0.0.1:5432/recruiter_demo_test \
  ava-audit-backend python -m scripts.benchmark_recruiter_demo /tmp/recruiter-benchmark.mp4 --linux-gate
docker stop ava-audit-db
```

The gate requires cgroup peak memory below 450 MiB, zero OOM events, successful jobs and grounded chat, and clean temporary storage. JSON output records elapsed time, Python and child-process CPU, cgroup CPU and memory, provider attempt counts, and logical temporary file bytes sampled at processing milestones. Mocked responses measure the local pipeline and application accounting. Live provider latency and quota behavior require separate evidence. [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/) · [Docker network namespaces](https://docs.docker.com/engine/network/#container-networks) · [pgvector image tags](https://github.com/pgvector/pgvector/tree/v0.8.1#docker)

## Local verification

- All 166 Python tests passed with disposable PostgreSQL and pgvector. Five frontend tests and the Vite production build passed.
- The browser opened the silent sample, sought to a cited timestamp, and made zero backend requests. Mocked live browser checks covered invited and public uploads, same-tab refresh, quota feedback, cited chat, deletion failure and success, and interrupted jobs.
- The macOS workload processed two 120-second clips and completed a chat during the second job. The first job took 2.24 seconds, the overlapping job and chat each took 0.30 seconds, and Python peak RSS was 381.4 MiB. These are local mocked-provider measurements. The Linux cgroup measurement is pending.
- After the provider failover update, the mocked workload again completed two jobs and an overlapping chat. Peak Python RSS was 380.7 MiB on macOS. The local Singapore Blueprint passed Render's published schema validation.
- The November 11, 2026 audit workload completed three 120-second uploads and three grounded chats on macOS arm64 using real FFmpeg, PostgreSQL 16, pgvector 0.8.1, and FlashRank. The cold upload and chat took 2.478 s and 0.068 s. The overlapping upload and chat took 0.337 s and 0.335 s. The warmed upload and chat took 0.304 s and 0.066 s.
- That audit run peaked at 427,245,568 bytes of Python RSS. CPU time was 3.231 s in Python and 0.652 s in child processes. The sampled temporary file peak was 4,987,220 bytes, with zero bytes left after cleanup. The workload intercepted 3 STT, 6 embedding, and 15 generation requests. It reserved 360,000 ms of audio, 42,006 input units, and 9,600 output tokens. These are measurements from one local run. The Docker build and cgroup gate were not run because the audit host had no Linux container runtime.
- The November 12, 2026 multi-provider update passed 213 backend tests in the Linux ARM64 image with PostgreSQL 16 and pgvector 0.8.1. The same image passed the strict workload at 512 MiB, zero swap, and 0.1 CPU. It peaked at 365.96 MiB of cgroup memory with zero OOM events. All three 120-second uploads and grounded chats completed, with six intercepted OpenRouter embedding requests and matching ledger entries. Cleanup left zero temporary media bytes. Cold upload and chat took 70.30 s and 2.41 s. Warm upload and chat took 13.20 s and 1.09 s. Native AMD64 verification of this update remains pending.

## Release order

Use [automatic sample deployment](SAMPLE_DEPLOYMENT.md) for the GitHub-driven sample stack. The sequence below records the hosting targets and the separate gates for enabling live analysis.

1. After push and deployment approval, create an empty Neon Free project in AWS Singapore (`aws-ap-southeast-1`). Deploy the approved commit to the new `ai-video-assistant-api-sg` Render Free service in Singapore with manual deploys, `sample` mode, and inference off. Set its `DATABASE_URL` to the new project and verify schema initialization and pgvector.
2. Deploy the static `web/` frontend on Vercel Hobby. Set its `VITE_BACKEND_URL` to the new Render URL and add the exact Vercel origin to `FRONTEND_ORIGIN` on Render. Verify the sample opens and seeks citations with the backend blocked. Set the cleanup workflow's `BACKEND_URL` and `ADMIN_TOKEN` to the new service and verify its target. Keep the old services until the replacement passes cutover checks if free capacity permits. The owner can then retire the old projects. The replacement starts with an empty database.
3. Before hosted live access, verify Vercel Hobby, Render Free bandwidth and build overage protection, Neon Free, and model entitlements for each configured route. Complete the Linux workload gate. After approval, enable `invited` with the [verified free generation routes](HYBRID_IMPLEMENTATION.md#provider-and-release-gates), verified Cloudflare or Gemini [embedding routes](HYBRID_IMPLEMENTATION.md#embedding-routes), and one English STT profile. Run a bounded synthetic smoke test and verify Render proxy identity and quota exhaustion behavior before opening `public`. [Render Free](https://render.com/docs/free) · [Vercel Hobby](https://vercel.com/docs/plans/hobby) · [Neon plans](https://neon.com/docs/introduction/plans)
4. Return to `invited` to restrict live submissions. Use `sample` and disable provider calls when a resource or billing gate fails. Keep capability checks enabled on any live rollback. Keep the separate Cloudflare MCP deployment outside this cutover.
