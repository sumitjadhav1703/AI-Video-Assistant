# Repository Guidelines

## Resume here

- Open `~/Projects/AI-Video-Assistant`. Use `ci/sample-stack` for [PR #4](https://github.com/sumitjadhav1703/AI-Video-Assistant/pull/4) while it is open. Start with `git status --short --branch` and check the PR head and CI before making changes.
- Read [roadmap status](docs/ROADMAP_STATUS.md) for measured results and pending gates. Use the [operator guide](docs/HYBRID_IMPLEMENTATION.md#local-setup) for disposable PostgreSQL with pgvector and verified provider configuration. The [sample deployment runbook](docs/SAMPLE_DEPLOYMENT.md) covers the separate hosted release.
- Preview Minutes at `http://127.0.0.1:5173/`. The standalone `/sample` uses prepared results and citations. The [browser test commands](docs/RECRUITER_DEMO.md#local-browser-checks) exercise the live-flow UI with intercepted requests. The API and CLI require verified provider accounts before live calls.
- Next, verify native AMD64 validation and the exact-image OS scan for the PR head. Verify free access for each configured account before an authorized synthetic live smoke test. Representative evaluation and hosted release checks follow. Keep the hosted stack in sample mode until its separate gates are cleared.
- Keep the existing `.env` private. Local evidence is in `output/handoff-verification/`. The retired checkouts are preserved locally in `output/local-checkout-archive/retired-checkouts.tar.gz`. Git ignores both.

## Project Structure & Module Organization

- `backend/api.py` defines FastAPI routes; `jobs.py` orchestrates processing; `db.py` persists job state.
- `backend/core/` contains transcription, summarization, extraction, RAG, and vector storage. `backend/utils/audio_processor.py` handles media acquisition, streaming chunks, and temporary-file cleanup.
- `web/src/` contains the React app, reusable `components/`, shared `lib/` helpers, and `styles.css`. Keep backend requests in `web/src/api.js`.
- `web/public/demo-clips/` holds the bundled recordings for the upload picker. `mcp-server/` contains the separate Cloudflare Worker.
- `Dockerfile` and `render.yaml` configure backend hosting; `web/vercel.json` configures frontend hosting. `.github/workflows/cleanup.yml` schedules data cleanup.
- `tests/` contains offline Python regression tests and opt-in local PostgreSQL tests. `web/src/api.test.js` tests frontend API error handling.

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

Remote provider calls default disabled. Do not enable them or add paid fallback without verifying free-only account access. Preserve durable usage counters and token-owned active slots; never reset them to bypass limits. Read `UPGRADE_IMPLEMENTATION_PLAN.md` before broader architecture changes.

## Sub-Agent Coordination & Tools

- The primary agent orchestrates all sub-agents: split work, assign clear scope and file ownership, track progress, review results, integrate changes, and verify the combined outcome.
- For multiple coding tasks, delegate independent work to sub-agents in parallel. Keep dependent tasks sequential and avoid concurrent edits to the same files.
- Use Sol (`gpt-6.1-sol`) or Terra (`gpt-6.1-terra`) for implementation, debugging, tests, and routine technical reviews. Use Astra (`gpt-6-astra`) for critical thinking, complex reasoning, and difficult architectural or research decisions; do not assign coding to Astra. Check available model identifiers before dispatch and report unavailable models rather than silently substituting.
- In every delegation, instruct sub-agents to discover and use relevant installed plugins, MCP tools, and skills available on this computer. Read applicable skill instructions first and prefer purpose-built tools when suitable. Preserve credential privacy and the local-only Git restriction across all agents.
