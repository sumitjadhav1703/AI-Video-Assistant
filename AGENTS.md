# Repository Guidelines

## Resume here

- Open `~/Projects/AI-Video-Assistant`. Work happens on `eval/deepeval-framework`, which has a PR open to `main`. Start with `git status --short --branch`, then check the PR head and CI before making changes.
- **Deployment state lives in two files.** [SUBMISSION_GUIDELINES.md](SUBMISSION_GUIDELINES.md) is the step-by-step chain a deployment agent (Cursor with Render, Vercel, Neon and Cloudflare MCPs) follows. [DEPLOYMENT_REPORT.md](DEPLOYMENT_REPORT.md) is what that agent filled in: URLs, service IDs, env var names set, each step's result and any errors. Read the report first when resuming after a deployment.
- Done on this branch: DeepEval evaluation ([evaluation report](evaluation/EVALUATION_REPORT.md)), the embedding fallback chain (Gemini, then Cloudflare Qwen, then the Nemotron routes, which are off on Render), the `/eval`, `/usage` and `/pipeline` pages (the old `/sample` page is removed and now serves the home page), the backend `GET /usage` endpoint, and the [engineering story](docs/engineering-story/README.md). The parked v2 RAG pipeline is in [future-improvements/v2-rag-pipeline](future-improvements/v2-rag-pipeline/README.md); none of it runs in the app.
- Read [roadmap status](docs/ROADMAP_STATUS.md) for measured results and pending gates. Use the [operator guide](docs/HYBRID_IMPLEMENTATION.md#local-setup) for disposable PostgreSQL with pgvector and verified provider configuration.
- Preview Minutes at `http://127.0.0.1:5173/` (plus `/eval`, `/usage`, `/pipeline`). The API and CLI need verified provider accounts before live calls.
- Next: merge the PR, deploy with the guide, then clear the hosted gates: proxy attribution on Render (one shared proxy IP would let a single upload use every visitor's daily allowance), a native AMD64 run on the merged head, and recovery of a stuck processing slot after a restart (`python -m backend.recover`).
- Keep the existing `.env` private. Local evidence is in `output/` (git-ignored; it contains secret-like strings, so never share or commit it).

## Project Structure & Module Organization

- `backend/api.py` defines FastAPI routes; `jobs.py` orchestrates processing; `db.py` persists job state.
- `backend/core/` contains transcription, summarization, extraction, RAG, and vector storage. `backend/utils/audio_processor.py` handles media acquisition, streaming chunks, and temporary-file cleanup.
- `web/src/` contains the React app, reusable `components/`, shared `lib/` helpers, and `styles.css`. Keep backend requests in `web/src/api.js`.
- `web/public/demo-clips/` holds the bundled recordings for the upload picker. `mcp-server/` contains the separate Cloudflare Worker.
- `Dockerfile` and `render.yaml` configure backend hosting; `web/vercel.json` configures frontend hosting. `.github/workflows/cleanup.yml` schedules data cleanup; `release.yml` deploys from `main` only when `DEPLOY_SAMPLE_STACK` is `true` (leave it unset while deploying manually with the guide).
- `tests/` contains offline Python regression tests and opt-in local PostgreSQL tests. `web/src/api.test.js` and `web/src/lib/parse.test.js` are the frontend unit tests (`npm test`). `web/tests/pages.browser.mjs` and `web/tests/live-session.browser.mjs` are Playwright browser checks. `evaluation/` holds the DeepEval framework and its reports.

## Build, Test, and Development Commands

Run backend commands from the repository root, preferably with Python 3.11 in a virtual environment:

- `python3.11 -m venv .venv` creates the local Python environment. Run `.venv/bin/python -m pip install -r backend/requirements.lock` and `.venv/bin/python scripts/prepare_reranker.py`. Install system `ffmpeg` separately.
- `uvicorn backend.api:app --host 127.0.0.1 --port 8000 --reload --no-access-log` starts the API without logging bearer job IDs.
- `python -m backend.cli` uses real providers and PostgreSQL. Reserve it for authorized smoke tests with verified free accounts.
- `docker build -t ai-video-backend .` builds the backend image; `docker run -p 8000:8000 --env-file .env ai-video-backend` starts it.
- In `web/`, run `npm ci`, then `npm run dev -- --host 127.0.0.1` for development, `npm run build` for production output, or `npm run preview` to inspect that build.

The development proxy defaults to `http://localhost:8000`; keep `web/.env` pointed at a local backend for routine checks.

## Coding Style & Naming Conventions

Use four-space indentation and `snake_case` for Python functions/modules. Use two-space indentation, `camelCase` functions, and `PascalCase` React components in JavaScript/JSX. Match surrounding quote and semicolon conventions. No formatter or linter is configured. Keep provider logic in `backend/core/` and preserve bounded-memory media processing.

## Testing Guidelines

Run `PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s tests -v` after installing the backend lockfile. Set `TEST_DATABASE_URL` to disposable loopback PostgreSQL with pgvector for integration tests. In `web/`, run `npm test` and `npm run build`. Add focused regression tests for behavior changes. Use mocked providers and disposable data for tests.

## Commit & Pull Request Guidelines

History uses prefixes such as `feat:`, `fix:`, `docs:`, and `ci:` with concise imperative descriptions. Keep changes scoped. PRs should explain behavior changes, link relevant issues, list validation and configuration changes, and include screenshots for UI changes.

## Security & Agent Instructions

Use `.env.example` templates. Keep credentials, cookies, transcripts, and private evidence out of Git. Preserve job/vector isolation and temporary-file cleanup. Use a development database for cleanup tests. Get explicit authorization for future pushes, merges, deployments, production migrations, and live provider calls.

Remote provider calls default disabled. Do not enable them or add paid fallback without verifying free-only account access. Preserve durable usage counters and token-owned active slots; never reset them to bypass limits. Read [docs/engineering-story/README.md](docs/engineering-story/README.md) before broader architecture changes. The earlier plan was removed; read it with `git show dfa7e60:UPGRADE_IMPLEMENTATION_PLAN.md`.

## Sub-Agent Coordination & Tools

- The primary agent orchestrates all sub-agents: split work, assign clear scope and file ownership, track progress, review results, integrate changes, and verify the combined outcome.
- For multiple coding tasks, delegate independent work to sub-agents in parallel. Keep dependent tasks sequential and avoid concurrent edits to the same files.
- Use Sol (`gpt-6.1-sol`) or Terra (`gpt-6.1-terra`) for implementation, debugging, tests, and routine technical reviews. Use Astra (`gpt-6-astra`) for critical thinking, complex reasoning, and difficult architectural or research decisions; do not assign coding to Astra. Check available model identifiers before dispatch and report unavailable models rather than silently substituting.
- In every delegation, instruct sub-agents to discover and use relevant installed plugins, MCP tools, and skills available on this computer. Read applicable skill instructions first and prefer purpose-built tools when suitable. Preserve credential privacy and the local-only Git restriction across all agents.
