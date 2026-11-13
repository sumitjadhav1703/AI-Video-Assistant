# Live performance

Measured on the deployed stack, from outside, like a real visitor. The goal is to know where time goes in production and what to improve next. Local and evaluation numbers are in [engineering-story/benchmarking-and-performance.md](engineering-story/benchmarking-and-performance.md) and [EVALUATION_REPORT §6](../evaluation/EVALUATION_REPORT.md).

**Status:** probes, page loads and the Worker are measured. The full pipeline run (upload → notes → questions) is **pending**: the first attempt was refused with `429` because the day's analysis allowance was already used. Rows marked *Pending* are filled after that run.

All numbers are single observations (n = 1 per row unless a count is given). Treat them as a first snapshot, not a benchmark.

## Environment

| Part | Where | Plan / limits |
|---|---|---|
| API | Render, Singapore, Docker image from `main` at `f0f03b2` | Free: 512 MiB RAM, shared CPU, sleeps after ~15 min idle |
| Database | Neon, AWS `ap-southeast-1` (Singapore), direct endpoint | Free |
| Web app | Vercel, `ai-video-assistant-silk.vercel.app` | Hobby, global CDN |
| MCP Worker | Cloudflare Workers, `ai-video-assistant-mcp.jadhavsumit534.workers.dev` | Free |
| Client | Owner's laptop on a mobile hotspot; Chromium (Playwright) for page loads; `curl` and [`scripts/measure_live.py`](../scripts/measure_live.py) for the API | Mobile network, so upload bandwidth is limited |
| Mode | `DEMO_LIVE_MODE=public`, provider calls on, free routes only | Deployment details: [DEPLOYMENT_REPORT.md](../DEPLOYMENT_REPORT.md) |

Measured on 2026-11-13, 20:00–20:35 UTC.

## How it was measured

- **API probes:** `curl -w '%{time_total}'` and `scripts/measure_live.py`. The script times `/health`, ten `/ready` calls, `/demo-mode` and `/usage`, then uploads one clip. It polls the job status every second to time each step change, asks three questions (one deliberately unanswerable) and deletes the job. It never prints the job token, transcript or answers.
- **Page loads:** Playwright opened each page in a fresh browser context ("first visit", empty cache), then again in the same context ("repeat visit"). Values come from the browser's Navigation Timing and Paint Timing APIs; bytes are transferred bytes.
- **Worker:** unauthenticated `POST /mcp` six times. It must answer `401`; this times the edge round trip and auth check without needing the bearer token.
- **Server-side stage timings** come from the API's own log lines (`metric=` / duration lines from [`backend/core/telemetry.py`](../backend/core/telemetry.py)), which hold sizes and timings only. They are added after the pipeline run.

## Results

### Backend availability and latency

| Measure | Result |
|---|---|
| Cold start (`/health` after the service slept) | **32.5 s** |
| `/health` when awake | 0.25 s |
| `/ready` when awake (database + pgvector check, n=10) | min 0.23 s, **p50 0.32 s**, p95 0.44 s, max 0.44 s |
| `/ready` right after the cold start | 0.91 s |
| `/demo-mode` when awake (n=3, time to first byte) | 0.19, 0.20, 0.37 s |
| `/demo-mode` and `/usage` as called by the web app (browser resource timing) | first visit 213 ms and 257 ms; repeat 130 ms and 145 ms |

### Web app page loads (Vercel)

| Page | Visit | Time to first byte | DOM ready | Load | First paint | Backend calls |
|---|---|---|---|---|---|---|
| `/` | first | 160 ms | 506 ms | 508 ms | 580 ms | `/demo-mode` 213 ms |
| `/` | repeat | 47 ms | 102 ms | 103 ms | 156 ms | `/demo-mode` 130 ms |
| `/eval` | first | 123 ms | 407 ms | 409 ms | 544 ms | none |
| `/eval` | repeat | 43 ms | 104 ms | 104 ms | 164 ms | none |
| `/usage` | first | 131 ms | 437 ms | 437 ms | 516 ms | `/usage` 257 ms |
| `/usage` | repeat | 37 ms | 95 ms | 96 ms | 144 ms | `/usage` 145 ms |
| `/pipeline` | first | 150 ms | 409 ms | 412 ms | 500 ms | none |
| `/pipeline` | repeat | 52 ms | 108 ms | 108 ms | 160 ms | none |

First visit transfers 96,203 bytes of JavaScript and 5,477 bytes of CSS (compressed); repeat visits load them from cache. No console errors on any page. The pages render without the backend, so a sleeping API never delays first paint.

### MCP Worker

| Measure | Result |
|---|---|
| Unauthenticated `POST /mcp` (n=6) | `401` every time; 1.16, 0.36, 0.38, 0.81, 0.31, 0.46 s |
| Authenticated tool calls | Pending (needs the bearer token; the deployment smoke test passed, see [DEPLOYMENT_REPORT.md](../DEPLOYMENT_REPORT.md)) |

### Analysis pipeline (pending)

| Stage | Outside timing (status polling, ±1 s) | Server timing (logs) |
|---|---|---|
| Upload request (733,251-byte, ~2-minute MP3) | Pending | `upload_copy`: Pending |
| Queued → audio (ffmpeg) | Pending | Pending |
| Transcription | Pending | Pending |
| Title | Pending | Pending |
| Summary | Pending | Pending |
| Findings | Pending | Pending |
| Embedding + indexing | Pending | Pending |
| Total, upload to notes ready | Pending | `time_to_result`: Pending |
| Peak memory during the job (Render Metrics) | — | Pending |

### Questions (pending)

| Question | Latency | Abstained | Citations | Model |
|---|---|---|---|---|
| What is generative AI, according to the speaker? | Pending | | | |
| What examples of generated content are mentioned? | Pending | | | |
| Who won the 2022 FIFA World Cup? (not in the clip) | Pending | | | |

## Findings so far

1. **Cold start dominates the first visit.** A sleeping API took 32.5 s to answer, about 100 times the awake `/ready` time. The app shows a "waking up" message, but every first visitor after 15 idle minutes waits.
2. **An over-limit upload waits for the whole file before it is refused.** The refused 733,251-byte upload took 25.3 s to get its `429`. The handler parses the full multipart body ([`backend/api.py`](../backend/api.py), `request.form()` at the start of `create_job`) before it checks the allowance (`db.admit_job`). On a slow mobile link the visitor uploads the entire file for nothing. The 25.3 s is mostly upload time on the mobile connection (about 29 KB/s effective), so a real job pays the same cost before processing starts.
3. **The allowance check is ambiguous to visitors.** `/usage` reports `analyses_today` as the smaller of the per-visitor and the site-wide allowance, so a `0` can mean either "you used yours" or "the site used all 5". The page does not say which.
4. **The frontend is fast and light.** Under 0.6 s to first paint on a first visit and under 0.17 s on repeat visits, with 96 KB of JavaScript. Not a bottleneck.
5. **The API is fast when awake.** `/ready`, which includes a database round trip to Neon in the same region, has a p50 of 0.32 s from the client, most of which is network distance from the client to Singapore.
6. **The Worker's first call is slower** (1.16 s against about 0.3–0.5 s afterwards): the edge isolate warming up.

## Improvement ideas (ranked by measured impact)

| # | Idea | Evidence | Expected effect | Cost / risk |
|---|---|---|---|---|
| 1 | Check the allowance before uploading: the web app calls `/usage` (already loaded on the home page) and disables Analyse with a clear message when `analyses_today` is 0 | Finding 2: 25.3 s wasted on a refused upload | Over-limit visitors get an instant answer instead of a full upload | Small frontend change; the server-side check stays authoritative |
| 2 | Reject over-limit uploads before reading the body: check admission from headers and the connection address first, then stream the file | Finding 2 | Same as 1 for clients that bypass the web app | Moderate: reorders `create_job`; must keep rollback-on-reject behaviour and tests |
| 3 | Shrink uploads in the browser for large files | Finding 2: about 29 KB/s on mobile | Less upload time on slow links | The earlier ffmpeg.wasm experiment saved only ~3% on already-compressed demo MP3s and adds 32 MB of wasm ([BROWSER_MEDIA_EXPERIMENT.md](BROWSER_MEDIA_EXPERIMENT.md)); worth it only for video files, where dropping the video track is the real saving |
| 4 | Say which limit was hit: return per-visitor and site-wide remaining separately in `/usage` and show both | Finding 3 | Visitors understand why they cannot upload | Small backend + frontend change |
| 5 | Wake the API when the web app loads, before the visitor picks a file (the home page already calls `/demo-mode`; show progress while it wakes) | Finding 1: 32.5 s cold start | Hides most of the cold start behind file selection | Small; a keep-alive pinger would avoid sleep entirely but uses free-tier hours and is against the free-tier spirit, so not recommended |
| 6 | Measure the pipeline stages on the live service, then target the slowest stage | Pipeline rows pending | Decides whether STT, notes or embeddings to optimise | None: scheduled |

## Still to measure

- The full pipeline and questions on the live service, with server stage timings from the logs and peak memory from Render Metrics.
- Whether visitors on different networks get separate allowances (the proxy-attribution question in [DEPLOYMENT_REPORT.md](../DEPLOYMENT_REPORT.md)).
- More than one run of each, at different times of day, to see variance and provider rate-limit effects.
- Authenticated MCP tool latency.

## Sources

- Probe and page-load raw values were recorded during the session; the reusable script is [`scripts/measure_live.py`](../scripts/measure_live.py).
- Handler order: [`backend/api.py`](../backend/api.py) `create_job` (form parse, then `db.admit_job`); allowance maths: `/usage` in the same file.
- Deployment configuration: [DEPLOYMENT_REPORT.md](../DEPLOYMENT_REPORT.md).
