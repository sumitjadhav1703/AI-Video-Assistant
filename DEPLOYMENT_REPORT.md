# Deployment report

Filled in by the deployment agent while following [SUBMISSION_GUIDELINES.md](SUBMISSION_GUIDELINES.md). Claude Code reads this file to resume work after deployment.

**Never write secret values here** (keys, tokens, passwords, connection strings). Write variable names, IDs, URLs and results only. Times in UTC.

Status values: ✅ done · ❌ failed · ⏸ stopped (waiting for owner/Claude) · ⏭ skipped (say why).

## Summary

| Field | Value |
|---|---|
| Deployment date (UTC) | 2026-11-13 |
| Deployed by | Cursor agent (+ owner approvals) |
| DEPLOY_SHA (`origin/main`) | f0f03b229b66fa3d6527d472cfb005d0065aec70 |
| Overall status | ✅ stack live (owner browser smoke + proxy-IP check still pending) |
| Stopped at step (if any) | |
| Live mode | public |
| RENDER_URL | https://ai-video-assistant-api-sg.onrender.com |
| VERCEL_URL | https://ai-video-assistant-silk.vercel.app |
| MCP Worker URL | https://ai-video-assistant-mcp.jadhavsumit534.workers.dev |

## Step results

| Step | Status | Time (UTC) | Notes (facts, IDs, check output, no secrets) |
|---|---|---|---|
| 0 Preflight | ✅ | 2026-11-13 | CI run ID: 43466550591 (Validate and release sample stack success on f0f03b2). Check runs: Backend/AMD64, Frontend, MCP all success. `.env` names present: GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_WORKERS_AI_TOKEN, LLM_ROUTES_JSON, LLM_TASK_ROUTES_JSON, STT_PROFILES_JSON, EMBEDDING_ROUTES_JSON, JOB_TOKEN_SECRET, RATE_LIMIT_SECRET. ADMIN_TOKEN empty locally (generated for deploy, not printed). Repo: https://github.com/sumitjadhav1703/AI-Video-Assistant.git. Files present: Dockerfile, render.yaml, web/, mcp-server/. |
| 1 Neon | ✅ | 2026-11-13 | project ID: dawn-mouse-87620513 · region: aws-ap-southeast-1 · branch: main (br-bitter-rain-a10n9mt0) · database: neondb · owner role name: neondb_owner · endpoint: ep-lucky-fog-a1aty0by (direct host, non-pooler) · `vector` extension: present |
| 2 Render | ✅ | 2026-11-13 | service ID: srv-dbrka2u1egvs73cl7da0 · deploy ID live: dep-dbrkah1v1jhc73daq3j0 (SHA f0f03b2) · first create deploy dep-dbrka3u1egvs73cl7ej0 status update_failed then env-triggered deploy went live · `/health`: ok · `/ready`: ok · `/demo-mode`: sample (then public in step 5) · `/usage`: JSON with limits+models · region singapore · plan free · autoDeploy off · Note: MCP create_web_service left healthCheckPath empty (could not set via available MCP tools) |
| 3 Vercel | ✅ | 2026-11-13 | project ID: prj_2KkZuE3gfsC6W9rezbHDxwhSV1QF · org/team ID: team_bBSzciTqMUSFmssa06Pht7XI · deployment ID: dpl_4RnrjH4oPyn1STnoJa7NEFy5tHN7 · Node 22.x · SSO disabled · `/` `/eval` `/usage` `/pipeline` codes: 200 each · VITE_BACKEND_URL set to RENDER_URL |
| 4 CORS | ✅ | 2026-11-13 | `FRONTEND_ORIGIN` set to: https://ai-video-assistant-silk.vercel.app · preflight header: access-control-allow-origin: https://ai-video-assistant-silk.vercel.app · redeploy dep-dbrkcdo8v5cc73bh6qj0 live |
| 5 Go public | ✅ (smoke ⏸ owner) | 2026-11-13 | `/demo-mode`: public · model lists non-empty: generation yes; embeddings gemini-embeddings+cloudflare-qwen; STT groq+gemini · redeploy dep-dbrkdfou01pc73don5mg live · smoke upload: pending owner browser · smoke question: pending owner · memory peak: not observed |
| 5 Proxy-IP check | ⏸ | 2026-11-13 | shared identity across networks? not tested (needs owner second network after smoke upload) |
| 6 Cleanup job | ✅ | 2026-11-13 | secrets set (names): BACKEND_URL, ADMIN_TOKEN · workflow run ID: 43472168584 · result: success · response: deleted=0 older_than_days=1 |
| 7a MCP DB roles | ✅ | 2026-11-13 | script result: setup-production.sql committed · reader checks: shared_jobs SELECT ok (0 rows); public.jobs denied |
| 7b Hyperdrive | ✅ | 2026-11-13 | Hyperdrive ID: e79981465fed4c0a80adb9493cca801a · caching disabled: yes · name: ai-video-assistant-mcp · origin user: ava_mcp_reader · host: ep-lucky-fog-a1aty0by.ap-southeast-1.aws.neon.tech |
| 7c Worker | ✅ | 2026-11-13 | Worker name: ai-video-assistant-mcp · hostname: ai-video-assistant-mcp.jadhavsumit534.workers.dev · version ID: d1a624ab-cf1e-415f-8db7-7f55f24f7615 · 401 check: pass · tools/list: 4 read-only tools · list_videos: success (0 items) |
| Final checklist F1–F9 | ✅ / ⏸ | 2026-11-13 | F1 ready ok · F2 public · F3 pages 200 · F4 smoke pending owner · F5 CORS ok · F6 cleanup ok · F7 worker ok · F8 free plans · F9 report filled |

## Environment variable names set (no values)

| Platform | Names |
|---|---|
| Render | ENABLE_PROVIDER_CALLS, DEMO_LIVE_MODE, ENABLE_PAID_META, ENABLE_PUBLIC_PAID_FALLBACK, ENABLE_NVIDIA_PUBLIC, ENABLE_SARVAM, ENABLE_YOUTUBE, ENABLE_GEMINI_EMBEDDINGS, MAX_UPLOAD_MB, MAX_MEDIA_SECONDS, JOBS_PER_IP_DAY, JOBS_GLOBAL_DAY, CHATS_PER_IP_MINUTE, CHATS_PER_IP_DAY, CHATS_PER_JOB_DAY, CHATS_GLOBAL_DAY, FRONTEND_ORIGIN, DATABASE_URL, JOB_TOKEN_SECRET, RATE_LIMIT_SECRET, ADMIN_TOKEN, GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_WORKERS_AI_TOKEN, LLM_ROUTES_JSON, LLM_TASK_ROUTES_JSON, STT_PROFILES_JSON, EMBEDDING_ROUTES_JSON |
| Vercel | VITE_BACKEND_URL |
| GitHub repository secrets | BACKEND_URL, ADMIN_TOKEN |
| Cloudflare Worker secrets | MCP_BEARER_TOKEN |
| Hyperdrive | origin user name only: ava_mcp_reader |

## Errors and fixes tried

One row per error. Copy the exact error message with any secret removed.

| Step | Time (UTC) | Error message | Playbook fix tried | Result |
|---|---|---|---|---|
| 2 Render | 2026-11-13 | First deploy dep-dbrka3u1egvs73cl7ej0 status `update_failed` (env not fully present at create) | Env vars set via update_environment_variables; new deploy dep-dbrkah1v1jhc73daq3j0 | Live; /health+/ready ok |
| 7c Worker | 2026-11-13 | `Invalid or missing CLOUDFLARE_API_TOKEN` from `scripts/release_worker.mjs` (wrangler OAuth JWT contains `.`, fails `/^[A-Za-z0-9_-]+$/`) | Deployed with wrangler OAuth + temp config (same bindings/hostname/hyperdrive as release script); ran equivalent smoke checks | Worker live; smoke passed |

## Deviations from the guidelines

1. Render `healthCheckPath` left empty — `create_web_service` MCP tool does not expose that field; service still responds correctly on `/health`.
2. Step 7c used `wrangler deploy` with a temporary config (not committed; `wrangler.jsonc` unchanged) instead of `node scripts/release_worker.mjs`, because no classic `CLOUDFLARE_API_TOKEN` matching the release script pattern was available (only wrangler OAuth JWT). Smoke checks matched the release script expectations.
3. `ADMIN_TOKEN` was generated by the agent (not present in local `.env`) and set on Render + GitHub; value never written to the report or chat.

## Open issues for Claude Code

1. Owner should complete browser smoke (upload 10–60s English clip + one question) on https://ai-video-assistant-silk.vercel.app and note result here.
2. Owner should check proxy-IP attribution from a second network (`/usage` analyses remaining) after smoke; if shared, leave as known issue (do not set FORWARDED_ALLOW_IPS).
3. Optional: set Render health check path to `/health` in the dashboard.
4. Optional: create a Cloudflare API token matching `[A-Za-z0-9_-]+` (Workers + Hyperdrive) if future deploys must use `scripts/release_worker.mjs` exactly.

## Owner notes

Anything the owner observed in the browser (smoke test, look of the pages, cold-start time).
