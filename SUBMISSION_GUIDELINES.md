# Submission guidelines: deploying Minutes (AI Video Assistant)

This file is the single source of truth for deploying this project. It is written for a **deployment agent** (Cursor, with the Render, Vercel, Neon and Cloudflare MCP servers connected) and for the **owner**, who approves each step and supplies secrets.

Deploy order: **Neon → Render → Vercel → CORS wiring → go public → cleanup job → MCP Worker (optional)**.

Everything the deployment agent does must be written into [DEPLOYMENT_REPORT.md](DEPLOYMENT_REPORT.md). After deployment, the owner will continue development with Claude Code, which reads that report to know exactly what was created, configured and what failed.

---

## 0. Rules for the deployment agent (read before doing anything)

1. **Deploy only. Do not change the project.** Do not edit, create, rename or delete any file in this repository, except [DEPLOYMENT_REPORT.md](DEPLOYMENT_REPORT.md). Do not commit, push, merge, open pull requests, change branches or rebase. Do not "fix" code, Dockerfiles, `render.yaml`, `vercel.json`, `wrangler.jsonc`, workflows or tests, even if a fix looks obvious.
2. **On any error:** stop the current step. Check the [error playbook](#11-error-playbook) for that symptom. You may try **only** the fix listed there, **once**. If it still fails, or the error is not listed: record the exact error text (with secrets removed), what you tried and the current state in `DEPLOYMENT_REPORT.md`. Then tell the owner: *"Deployment stopped at step X. Details are in DEPLOYMENT_REPORT.md. Please ask Claude Code for the fix."* Do not improvise further.
3. **Secrets never appear in output.** Never print, echo, log, paste into chat, write to the report, or commit any secret value (API keys, tokens, passwords, connection strings, `.env` contents). Pass them directly into the platform's secret/env-var tool. In the report, write variable **names** only. If a tool's output shows a secret, do not repeat it.
4. **Free tiers only.** Render plan `free`, Vercel Hobby, Neon Free, Cloudflare Workers Free. Never choose a paid plan, add a payment method, upgrade an instance, or enable a paid add-on. If a step seems to need payment, stop and report.
5. **Never enable paid or unsafe settings:** keep `ENABLE_PAID_META=false`, `ENABLE_PUBLIC_PAID_FALLBACK=false`, `ENABLE_NVIDIA_PUBLIC=false`, `ENABLE_SARVAM=false`, `ENABLE_YOUTUBE=false`, `ENABLE_API_DOCS` unset. Never set `FORWARDED_ALLOW_IPS=*` or add `--proxy-headers`. Never set any `LANGCHAIN_TRACING*` / `LANGSMITH_TRACING` variable.
6. **Never touch usage data.** Do not delete, reset or edit rows in `usage_counters`, `usage_slots`, `usage_guard`, `audio_attempts` or `jobs`. Do not run `python -m backend.recover` without the owner's explicit OK (see playbook).
7. **Do not enable the GitHub release automation.** Leave the GitHub variable `DEPLOY_SAMPLE_STACK` unset (or `false`). This guide deploys manually through MCP; turning automation on as well would make two systems deploy the same services.
8. **Ask before every create/modify action** on a cloud platform (create project, set env vars, deploy, run SQL). Read-only checks need no approval.
9. Work through the steps **in order**. Each step ends with a ✅ check. Do not start the next step until the check passes and is recorded.

---

## 1. What the owner does first

Do these before handing this file to the deployment agent.

| # | Owner action | How |
|---|---|---|
| O1 | Merge the open pull request from `eval/deepeval-framework` into `main` | GitHub → Pull requests → review → wait for CI checks to pass → **Merge**. All platforms deploy from `main`. |
| O2 | Confirm the local `.env` has the provider keys | It must contain values for `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_WORKERS_AI_TOKEN`, plus `LLM_ROUTES_JSON`, `LLM_TASK_ROUTES_JSON`, `STT_PROFILES_JSON`, `EMBEDDING_ROUTES_JSON`. The route JSON values contain only key *names*, never key values. |
| O3 | Generate four new random secrets (do not reuse local ones) | Run once per secret in a terminal and keep the output private: `openssl rand -base64 48 \| tr -d '\n=+/' \| cut -c1-48`. Needed: `JOB_TOKEN_SECRET`, `RATE_LIMIT_SECRET`, `ADMIN_TOKEN`, and (for the Worker) `MCP_BEARER_TOKEN` (see step 7 for its special format). Store them in a password manager. |
| O4 | Be signed in to Render, Vercel, Neon, Cloudflare and GitHub in the MCP connections | Each MCP server in Cursor must show as connected. |
| O5 | Approve each agent action | Read what the agent is about to create or change before approving. |
| O6 | Final check in a browser | After step 5, open the Vercel URL, upload a short clip (10–60 s, English speech), ask one question. |

Free-tier facts the owner should know:
- **Render Free sleeps after ~15 minutes idle.** The first request after sleep takes about a minute; the app shows a "waking up" hint.
- **Daily limits are deliberate:** 1 analysis per visitor per day, 5 across all visitors, 2 questions per minute and 15 per day per visitor, 3 per recording ([`backend/usage_limits.py`](backend/usage_limits.py), [`render.yaml`](render.yaml)).
- **One upload at a time** across the whole site (one global processing slot).

---

## 2. Step 0: preflight (read-only)

| Check | Command / action | Expected |
|---|---|---|
| Repo is the right one | `git remote get-url origin` | `https://github.com/sumitjadhav1703/AI-Video-Assistant.git` |
| `main` contains the merged work | `git fetch origin && git log --oneline -1 origin/main` | The merge commit of the PR from O1 |
| Deployed SHA | `git rev-parse origin/main` | Record this 40-character SHA as **DEPLOY_SHA** in the report |
| Files present on `main` | `git show origin/main --stat -1` then `git ls-tree origin/main --name-only` | `render.yaml`, `Dockerfile`, `web/`, `mcp-server/` present |
| CI passed | GitHub → Actions → latest run on `main` (or `gh run list --branch main --limit 3`) | Success. If CI failed, stop and report. |
| `.env` names exist (names only!) | `grep -o '^[A-Z_]*=' .env \| sort` | The names listed in O2 are present. **Never print values.** |

✅ Record DEPLOY_SHA and the check results in the report.

---

## 3. Step 1: Neon (database)

1. Create (or reuse, if the owner says so) a **Neon Free** project. Region: **AWS Asia Pacific (Singapore) `aws-ap-southeast-1`**, close to the Render Singapore region. Name suggestion: `ai-video-assistant`.
2. Use the default branch (`main`) and default database (`neondb`) unless the owner chooses otherwise.
3. Enable pgvector: run `CREATE EXTENSION IF NOT EXISTS vector;` in the Neon SQL editor (or via the Neon MCP). The app also runs this on startup, but running it now confirms the role is allowed to.
4. Get the **direct (non-pooled) connection string** for the database owner role. Its host does **not** contain `-pooler`. It must end with `?sslmode=require`. This is `DATABASE_URL` for Render. Keep it secret.
   - Why direct: the backend keeps very few connections and some database code assumes session behaviour; Neon's pooled endpoint uses transaction pooling.
5. Do **not** create tables manually. The backend creates its schema on first start (`backend/db.py` `init_db`).

✅ Check: `SELECT extname FROM pg_extension WHERE extname = 'vector';` returns one row. Record project ID, region, branch, database name and role **name** (not password) in the report.

---

## 4. Step 2: Render (backend API)

### 2a. Create the service

Create a **Web Service** from the GitHub repo `sumitjadhav1703/AI-Video-Assistant` with exactly these settings (they mirror [`render.yaml`](render.yaml); the release checks in `scripts/release_render.py` expect them):

| Setting | Value |
|---|---|
| Name | `ai-video-assistant-api-sg` |
| Runtime | Docker |
| Dockerfile path | `./Dockerfile` |
| Docker build context | repository root |
| Branch | `main` |
| Region | Singapore |
| Plan | **Free** |
| Health check path | `/health` |
| Auto-deploy | **Off** (deploys are triggered manually) |
| Start command | leave empty (the Dockerfile's `CMD` runs `uvicorn ... --no-access-log`; do not add proxy flags) |

### 2b. Environment variables (first boot = safe mode)

Set these **before** the first deploy. First boot runs with providers **off** and mode `sample`, so health and database checks happen with zero model calls.

Plain values (not secret):

| Name | Value |
|---|---|
| `ENABLE_PROVIDER_CALLS` | `false` (changes to `true` in step 5) |
| `DEMO_LIVE_MODE` | `sample` (changes to `public` in step 5) |
| `ENABLE_PAID_META` | `false` |
| `ENABLE_PUBLIC_PAID_FALLBACK` | `false` |
| `ENABLE_NVIDIA_PUBLIC` | `false` |
| `ENABLE_SARVAM` | `false` |
| `ENABLE_YOUTUBE` | `false` |
| `ENABLE_GEMINI_EMBEDDINGS` | `false` (embeddings use `EMBEDDING_ROUTES_JSON` instead) |
| `MAX_UPLOAD_MB` | `25` |
| `MAX_MEDIA_SECONDS` | `600` |
| `JOBS_PER_IP_DAY` | `1` |
| `JOBS_GLOBAL_DAY` | `5` |
| `CHATS_PER_IP_MINUTE` | `2` |
| `CHATS_PER_IP_DAY` | `15` |
| `CHATS_PER_JOB_DAY` | `3` |
| `CHATS_GLOBAL_DAY` | `15` |
| `FRONTEND_ORIGIN` | `http://localhost:5173` for now (replaced in step 4) |

Secret values (set via the Render MCP secret/env tool; never print):

| Name | Source |
|---|---|
| `DATABASE_URL` | Neon direct connection string from step 1 |
| `JOB_TOKEN_SECRET` | Owner's new secret (O3), at least 32 characters |
| `RATE_LIMIT_SECRET` | Owner's new secret (O3), at least 32 characters, different from the one above |
| `ADMIN_TOKEN` | Owner's new secret (O3) |
| `GROQ_API_KEY` | local `.env` |
| `GEMINI_API_KEY` | local `.env` |
| `OPENROUTER_API_KEY` | local `.env` |
| `CLOUDFLARE_ACCOUNT_ID` | local `.env` |
| `CLOUDFLARE_WORKERS_AI_TOKEN` | local `.env` |
| `LLM_ROUTES_JSON` | local `.env` (copy the exact single-line JSON) |
| `LLM_TASK_ROUTES_JSON` | local `.env` |
| `STT_PROFILES_JSON` | local `.env` |
| `EMBEDDING_ROUTES_JSON` | local `.env` |

Do **not** set: `META_API_KEY`, `SARVAM_API_KEY`, `NVIDIA_API_KEY`, `MISTRAL_API_KEY`, `GOOGLE_API_KEY`, `DEMO_INVITE_CODE`, `OWNER_EVALUATION_TOKEN`, `ENABLE_API_DOCS`, `FORWARDED_ALLOW_IPS`, any `LANGCHAIN_*` / `LANGSMITH_*`. Do not set `PORT` (Render provides it) or `RENDER` (Render sets it; it automatically disables the OpenRouter and NVIDIA embedding routes, which is intended).

How to copy from `.env` without printing: read the file inside a tool call and pass each value straight into the Render env-var tool. If the MCP tool cannot take a value without echoing it, ask the owner to paste that value into the Render dashboard (Service → Environment) instead.

### 2c. Deploy and verify

Trigger a manual deploy of `main`. The Docker build takes several minutes (it downloads the reranker model at build time). Wait until the deploy is **Live**.

Let `RENDER_URL` be the service URL, for example `https://ai-video-assistant-api-sg.onrender.com` (use the real one).

| Check | Command | Expected |
|---|---|---|
| Process up | `curl -s $RENDER_URL/health` | `{"status":"ok"}` (first call may take ~60 s on a cold start) |
| Database + pgvector | `curl -s $RENDER_URL/ready` | `{"status":"ok"}` |
| Mode | `curl -s $RENDER_URL/demo-mode` | `"mode":"sample"` |
| Usage endpoint | `curl -s $RENDER_URL/usage` | JSON with `limits` and `models`; `remaining` is null in sample mode |
| Logs clean | Render logs for this deploy | No `Traceback`, no `out of memory` |

✅ Record service ID (`srv-...`), `RENDER_URL`, deploy ID, the four check results, and the env var **names** set.

---

## 5. Step 3: Vercel (frontend)

1. Create a Vercel project from the same GitHub repo, team = the owner's Hobby account.
2. Settings:

| Setting | Value |
|---|---|
| Framework preset | Vite |
| Root directory | `web` |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Output directory | `dist` |
| Node.js version | 22.x (or 24.x) |
| Production branch | `main` |

3. Environment variable (Production): `VITE_BACKEND_URL` = `RENDER_URL` with **no trailing slash**. It is not a secret, but it is baked into the build, so set it **before** building. Do not add any backend secret to Vercel.
4. Note: [`web/vercel.json`](web/vercel.json) has `"git": {"deploymentEnabled": false}`, so pushes do not auto-deploy. Deploy explicitly: a production deployment of `main` through the Vercel MCP, or from a clean checkout of `main`: `cd web && npx vercel@latest deploy --prod` (after `vercel link` to this project). Do not edit `vercel.json`.
5. Let `VERCEL_URL` be the production URL (for example `https://<project>.vercel.app`).

| Check | Command / action | Expected |
|---|---|---|
| Home | open `VERCEL_URL/` | "Drop a recording here." and links Evaluation · Usage · How it works |
| Deep links (rewrite works) | `curl -s -o /dev/null -w '%{http_code}' $VERCEL_URL/eval` (also `/usage`, `/pipeline`) | `200` each |
| Backend URL baked in | Browser devtools Network tab on `/usage` | Request goes to `RENDER_URL/usage` (it may fail CORS until step 4; that is expected) |

✅ Record project ID (`prj_...`), team/org ID, `VERCEL_URL`, deployment ID.

---

## 6. Step 4: connect frontend and backend (CORS)

1. On Render, set `FRONTEND_ORIGIN` = `VERCEL_URL` exactly (scheme + host, no path, no trailing slash). If the owner also uses a custom domain, list both separated by a comma, no spaces.
2. **Redeploy the Render service** (CORS origins are read only at startup).
3. Verify:

```bash
curl -s -i -X OPTIONS "$RENDER_URL/jobs" \
  -H "Origin: $VERCEL_URL" \
  -H "Access-Control-Request-Method: POST" | grep -i access-control-allow-origin
```

Expected: `access-control-allow-origin: <VERCEL_URL>` exactly.

4. Open `VERCEL_URL/usage` in a browser: the allowance section should load (it will say live analysis is paused, because mode is still `sample`).

✅ Record the result.

---

## 7. Step 5: go public (the owner chose public mode)

1. On Render set `ENABLE_PROVIDER_CALLS=true` and `DEMO_LIVE_MODE=public`. Keep every setting in rule 5 unchanged.
2. Redeploy. Wait for Live. Recheck `/health`, `/ready`, and `curl -s $RENDER_URL/demo-mode` → `"mode":"public"`.
3. `curl -s $RENDER_URL/usage`: `models.generation`, `models.embeddings` and `models.speech_to_text` must each be non-empty. If any is empty, a route JSON or key is missing (see playbook).
4. **Smoke test (owner, in a browser):** open `VERCEL_URL`, upload one short English clip (10–60 s, under 25 MiB), wait for the result (title, summary, findings, transcript), then ask one question. Expect an answer with a quoted citation. This uses 1 of the 5 daily analyses and 1 question.
5. **Proxy-IP check (important):** in Render logs, find the lines for the smoke upload. The app identifies visitors by connection address. If Render's proxy hides real visitor addresses, **every visitor shares one identity**, so the first upload of the day would block everyone else (limit is 1 per visitor per day).
   - How to check: after the owner's upload, ask the owner to open `VERCEL_URL/usage` from a **different network** (for example a phone on mobile data). If "Analyses left today" shows `0` there too, visitors share one identity.
   - If they share one identity: **do not change any proxy setting.** Record it in the report as an open issue and tell the owner. Leaving `public` on still works (5 analyses per day total, first come first served), or the owner can set `DEMO_LIVE_MODE=sample` to pause. The proper fix needs a code change; ask Claude Code.
6. Watch Render memory for the smoke upload (Metrics tab). The free instance has 512 MiB; local tests peaked around 425 MiB. Record the peak if visible.

✅ Record mode, model lists (names only), smoke result, proxy-IP finding, memory observation.

---

## 8. Step 6: daily cleanup job (GitHub)

The workflow [`.github/workflows/cleanup.yml`](.github/workflows/cleanup.yml) runs daily at 03:00 UTC and deletes recordings older than 1 day through `POST /admin/cleanup`.

1. In GitHub → repo → Settings → Secrets and variables → Actions → **Repository secrets**, set:
   - `BACKEND_URL` = `RENDER_URL`
   - `ADMIN_TOKEN` = the same value set on Render
   (Owner can do this, or the agent with `gh secret set BACKEND_URL` / `gh secret set ADMIN_TOKEN`, entering the value at the prompt; never on the command line.)
2. Run it once: GitHub → Actions → cleanup → **Run workflow** (or `gh workflow run cleanup.yml`). Expected: success (it retries for cold starts).
3. Do **not** set `DEPLOY_SAMPLE_STACK` or the `sample-deployment` environment (rule 7).

✅ Record the workflow run ID and result.

---

## 9. Step 7: MCP Worker on Cloudflare (optional, last)

The Worker exposes 4 **read-only** MCP tools (`list_videos`, `get_job_status`, `get_video_summary`, `get_transcript`) for jobs the owner explicitly shares. It reads Neon through Hyperdrive using a restricted reader role. Background: [docs/mcp-cloudflare/](docs/mcp-cloudflare/README.md).

**7a. Database roles (run once, needs owner approval: this is DDL on the live database).**
Only after step 2 succeeded (tables exist). As the Neon owner role, in `psql` from the repo root:

```sql
\set ON_ERROR_STOP on
\i mcp-server/setup-production.sql
\password ava_mcp_reader
ALTER ROLE ava_mcp_reader LOGIN;
```

`\password` prompts for a new password; the owner types a fresh one (keep it; it goes into Hyperdrive). The script fails if the roles already exist; if so, stop and report (do not drop anything).

Verify as `ava_mcp_reader`: `SELECT job_id FROM ava_mcp.shared_jobs LIMIT 1;` works (0 rows is fine); `SELECT * FROM public.jobs LIMIT 1;` is **denied**.

**7b. Hyperdrive.** Create a Hyperdrive config (Cloudflare dashboard or MCP) named `ai-video-assistant-mcp`:
- Origin: Neon **direct** host, port 5432, database `neondb`, user `ava_mcp_reader`, the reader password.
- **Caching: disabled.** TLS verified.
Record the Hyperdrive ID (32 hex characters).

**7c. Worker secret and deploy.** The bearer token must be the base64url encoding of 32 random bytes (exactly 43 characters):

```bash
node -e 'console.log(require("node:crypto").randomBytes(32).toString("base64url"))'
```

The owner runs that and keeps the value private. Then from a clean checkout of `main`:

```bash
cd mcp-server && npm ci
npx wrangler secret put MCP_BEARER_TOKEN   # paste the token at the prompt; if asked to create the Worker first, answer yes
```

Deploy with the repo's release script (it injects the real account, hostname and Hyperdrive ID into a temporary config, deploys, and runs the read-only smoke test; it does not edit `wrangler.jsonc`). From the repo root, with these set in the shell environment (values never echoed):
- `CLOUDFLARE_API_TOKEN` (a token scoped to Workers + Hyperdrive for this account)
- `CLOUDFLARE_ACCOUNT_ID`
- `MCP_HOSTNAME` = `ai-video-assistant-mcp.<account-subdomain>.workers.dev`
- `MCP_HYPERDRIVE_ID` = from 7b
- `MCP_SMOKE_TOKEN` = the same token as `MCP_BEARER_TOKEN`
- `RELEASE_SHA` = DEPLOY_SHA

```bash
node scripts/release_worker.mjs
```

Expected: it reports the deployed version at 100% and passes: unauthenticated request → HTTP 401; `tools/list` → exactly the 4 tools; `list_videos` → success.

✅ Record Worker name, hostname, version ID, Hyperdrive ID, smoke result. Never record the token.

---

## 10. Final checklist

| # | Check | Expected |
|---|---|---|
| F1 | `curl -s $RENDER_URL/ready` | `{"status":"ok"}` |
| F2 | `curl -s $RENDER_URL/demo-mode` | `public` |
| F3 | `VERCEL_URL/`, `/eval`, `/usage`, `/pipeline` | All load; `/usage` shows live allowance |
| F4 | Smoke upload + question | Result and cited answer |
| F5 | CORS preflight | Exact Vercel origin echoed |
| F6 | Cleanup workflow | Last run succeeded |
| F7 | Worker (if deployed) | 401 without token; 4 tools with token |
| F8 | Billing pages | Render, Vercel, Neon, Cloudflare all on free plans; no payment method added by this deployment |
| F9 | `DEPLOYMENT_REPORT.md` | Every section filled in; no secret values anywhere in it |

When F1–F9 are done, tell the owner deployment is complete and point to the report. The agent's work ends here.

---

## 11. Error playbook

"Allowed fix" is the only thing the deployment agent may try, once. Anything else: record and stop (rule 2).

| Symptom | Likely cause | Allowed fix | If it still fails |
|---|---|---|---|
| Render build fails at `pip install` or `prepare_reranker.py` | Transient network/download error | Re-run the deploy once ("Clear build cache & deploy") | Record the last 40 log lines (no secrets) and stop |
| Render build fails elsewhere (Dockerfile step, `apt-get`) | Image/base change | None | Record and stop |
| Deploy "Live" but `/health` times out | Cold start on Free plan | Wait 90 s, retry 3 times | Record and stop |
| `/health` ok, `/ready` returns 503 | `DATABASE_URL` wrong, missing `sslmode=require`, or pgvector missing | Re-check the value is the **direct** string with `?sslmode=require` (re-enter it without printing); confirm `CREATE EXTENSION vector` ran; redeploy | Record and stop |
| Startup log: `RATE_LIMIT_SECRET must contain at least 32 characters` (or similar for `JOB_TOKEN_SECRET`) | Secret too short or missing | Owner generates a new 48-character secret (O3) and sets it; redeploy | Record and stop |
| Startup log mentions `LANGCHAIN_TRACING` / tracing refused | A tracing variable is set | Remove that variable; redeploy | Record and stop |
| Container restarts, `out of memory` / exit 137 | 512 MiB exceeded | None (do not upgrade the plan) | Record the time, upload size and log lines; set `DEMO_LIVE_MODE=sample`, redeploy; stop |
| Vercel build fails | Wrong root directory or Node version | Confirm root `web`, Node 22.x, build `npm run build`, output `dist`; redeploy once | Record and stop |
| Vercel `/eval` or `/usage` returns 404 | `vercel.json` rewrite not applied (wrong root dir) | Confirm root directory is `web`; redeploy | Record and stop |
| Browser shows CORS error / `/usage` "unavailable" | `FRONTEND_ORIGIN` mismatch or Render not redeployed | Set it to the exact origin (no trailing slash), redeploy Render, re-run step 4 check | Record and stop |
| Frontend calls `localhost:8000` | `VITE_BACKEND_URL` missing at build time | Set it in Vercel Production env and redeploy | Record and stop |
| Upload returns 503 "Provider calls are disabled" | `ENABLE_PROVIDER_CALLS` still `false` | Set `true` (step 5) and redeploy | Record and stop |
| Upload returns 429 | Daily or per-visitor limit reached (by design) | None. Note the `Retry-After` value | Record; not an error |
| Upload returns 503 "busy" / processing slot held | Another job running, or a previous job crashed and left the slot held | Wait 10 minutes and retry once | Do **not** run recovery. Record and ask the owner; recovery (`python -m backend.recover`) needs Claude's guidance and the owner's OK |
| `/usage` shows an empty model list | Route JSON or matching key missing | Re-check the four route JSON variables and the keys they reference by name (`api_key_env`, `keyenv`); redeploy | Record which list is empty and stop |
| Job fails at "Embedding" | Gemini quota exhausted and Cloudflare token lacks Workers AI permission | None (keys belong to the owner) | Record the error text and stop |
| Chat answers "I could not find this information" for an obvious question | Possible retrieval/model issue | None | Record the question and job time; stop |
| Cleanup workflow fails with 401/403 | `ADMIN_TOKEN` differs between GitHub and Render | Owner re-enters the same value in both; re-run | Record and stop |
| `setup-production.sql` fails: role/schema exists | Already installed earlier | None. Do not drop roles | Record and stop |
| `release_worker.mjs`: `Invalid or missing <NAME>` | An env var missing or wrong format | Fix that variable's format (see 7c) and re-run once | Record and stop |
| Worker smoke: not 401 without token, or wrong tool list | Wrong config or secret | None | Record and stop; consider deleting the deployment only if the owner says so |
| Hyperdrive cannot connect | Wrong host (pooled) / password / caching on | Use the direct host and reader user; disable caching | Record and stop |
| Any platform asks for a payment method or plan upgrade | Free limit reached or wrong plan | None | Stop immediately and report |

---

## 12. Rollback

- **Pause the live app (safest, instant):** on Render set `DEMO_LIVE_MODE=sample` and `ENABLE_PROVIDER_CALLS=false`, redeploy. The site stays up; uploads are closed.
- **Bad backend deploy:** Render → service → Deploys → roll back to the previous Live deploy.
- **Bad frontend deploy:** Vercel → Deployments → promote the previous production deployment.
- **Worker:** Cloudflare → Worker → Deployments → roll back; to cut database access immediately: `ALTER ROLE ava_mcp_reader NOLOGIN;` (owner approval).
- Never delete the Neon project or its data as a rollback step.

---

## 13. Hand-back

Fill every section of [DEPLOYMENT_REPORT.md](DEPLOYMENT_REPORT.md) as you go (not only at the end). It is the only record Claude Code will have of what happened. Write facts: names, IDs, URLs, timestamps (UTC), command results, exact error messages with secrets removed. If you deviated from this guide in any way, write what and why in the "Deviations" section.
