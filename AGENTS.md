# Repository Guidelines

## Project Structure & Module Organization

- `backend/api.py` defines FastAPI routes; `jobs.py` orchestrates processing; `db.py` persists job state.
- `backend/core/` contains transcription, summarization, extraction, RAG, and vector storage. `backend/utils/audio_processor.py` handles media acquisition, streaming chunks, and temporary-file cleanup.
- `web/src/` contains the React app, reusable `components/`, shared `lib/` helpers, and `styles.css`. Keep backend requests in `web/src/api.js`.
- `Dockerfile` and `render.yaml` configure backend hosting; `web/vercel.json` configures frontend hosting. `.github/workflows/cleanup.yml` schedules data cleanup.
- `tests/` contains offline Python regression tests and opt-in local PostgreSQL tests. `web/src/api.test.js` tests frontend API error handling.

## Build, Test, and Development Commands

Run backend commands from the repository root, preferably with Python 3.11 in a virtual environment:

- `pip install -r backend/requirements.lock` installs the tested Python 3.11 dependencies; install system `ffmpeg` separately.
- `uvicorn backend.api:app --host 127.0.0.1 --port 8000 --reload --no-access-log` starts the API without logging bearer job IDs.
- `python -m backend.cli` uses real providers and PostgreSQL. Reserve it for authorized smoke tests with verified free accounts.
- `docker build -t ai-video-backend .` builds the backend image; `docker run -p 8000:8000 --env-file .env ai-video-backend` starts it.
- In `web/`, run `npm install`, then `npm run dev` for development, `npm run build` for production output, or `npm run preview` to inspect that build.

The development proxy defaults to `http://localhost:8000`; keep `web/.env` pointed at a local backend for routine checks.

## Coding Style & Naming Conventions

Use four-space indentation and `snake_case` for Python functions/modules. Use two-space indentation, `camelCase` functions, and `PascalCase` React components in JavaScript/JSX. Match surrounding quote and semicolon conventions. No formatter or linter is configured. Keep provider logic in `backend/core/` and preserve bounded-memory media processing.

## Testing Guidelines

Run `python -m unittest discover -s tests -v` after installing the backend lockfile. Set `TEST_DATABASE_URL` only to disposable loopback PostgreSQL for transaction tests. In `web/`, run `npm test` and `npm run build`. No coverage threshold is configured. Add focused regression tests for behavior changes. Keep providers mocked and never use a production database for tests.

## Commit & Pull Request Guidelines

History uses prefixes such as `feat:`, `fix:`, `docs:`, and `ci:` with concise imperative descriptions. Keep changes scoped. PRs should explain behavior changes, link relevant issues, list validation and configuration changes, and include screenshots for UI changes.

## Security & Agent Instructions

Use `.env.example` templates; never commit credentials, cookies, or transcripts. Preserve job/vector isolation and temporary-file cleanup. Cleanup endpoints delete data: use a development database. Keep work on `work/project-updates`; do not push or publish PRs until explicitly authorized.

Remote provider calls default disabled. Do not enable them or add paid fallback without verifying free-only account access. Preserve durable usage counters and token-owned active slots; never reset them to bypass limits. Read `UPGRADE_IMPLEMENTATION_PLAN.md` before broader architecture changes.

## Sub-Agent Coordination & Tools

- The primary agent orchestrates all sub-agents: split work, assign clear scope and file ownership, track progress, review results, integrate changes, and verify the combined outcome.
- For multiple coding tasks, delegate independent work to sub-agents in parallel. Keep dependent tasks sequential and avoid concurrent edits to the same files.
- Use Sol (`gpt-6.1-sol`) or Terra (`gpt-6.1-terra`) for implementation, debugging, tests, and routine technical reviews. Use Astra (`gpt-6-astra`) for critical thinking, complex reasoning, and difficult architectural or research decisions; do not assign coding to Astra. Check available model identifiers before dispatch and report unavailable models rather than silently substituting.
- In every delegation, instruct sub-agents to discover and use relevant installed plugins, MCP tools, and skills available on this computer. Read applicable skill instructions first and prefer purpose-built tools when suitable. Preserve credential privacy and the local-only Git restriction across all agents.
