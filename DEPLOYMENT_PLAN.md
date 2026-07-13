# AI Video Assistant — Deployment Refactor Plan

## ⚠️ HARD RULES — READ FIRST, DO NOT VIOLATE

1. **DO NOT open, read, print, log, or reference the contents of any `.env` file** in this project, under any circumstances. It contains live API keys (Mistral, Sarvam, Groq, database credentials). You may reference *variable names* (e.g. `MISTRAL_API_KEY`) but never their values.
2. If you need an environment variable that doesn't exist yet, **add its name to `.env.example`** (a placeholder file with no real values) and tell the user to fill in the real value in their actual `.env` themselves. Never ask the user to paste a key into chat.
3. Work only on the existing codebase already in this repository. Do not discard or rewrite files from scratch when a targeted edit will do — preserve existing logic, naming, and structure wherever it isn't the specific thing being changed.
4. If a task in this plan requires an external account, dashboard click, or manual signup (anything outside this codebase), **stop, list it clearly as a manual step for the user, and move to the next task** you can still do autonomously. Do not block on it.
5. At the end, produce a summary of: (a) everything you completed, (b) everything you could not do and why, (c) the exact manual steps the user must still do themselves.

---

## Context

This is an AI Video Assistant: takes a YouTube URL or uploaded file, transcribes it, summarizes it, extracts action items/decisions/questions, and lets the user chat with the transcript via RAG. It currently runs as a single local Python process (CLI-based, `main.py`). The goal is to split it into a deployed backend + frontend, fix known bugs, and swap out components that won't survive free-tier hosting constraints.

## Target Architecture

- **Backend**: FastAPI app deployed on **Render** (free tier)
- **Frontend**: Streamlit app deployed on **Streamlit Community Cloud** (free tier)
- **Speech-to-text**: **Groq API** (`whisper-large-v3-turbo`) for English, replacing local `openai-whisper` + `torch`. Keep existing Sarvam integration for Hinglish, unchanged.
- **Persistent storage**: **Neon** (serverless Postgres with pgvector extension) for job results and RAG vectors, replacing local Chroma + in-memory-only storage.
- **YouTube downloads**: `yt-dlp` with a browser-exported `cookies.txt` to reduce (not eliminate) datacenter-IP blocking.

---

## Task 1 — Fix existing bugs (do this first, before anything else)

1. **Case-sensitivity bug**: Find the RAG engine file. If it's named with a capital letter (e.g. `Rag_engine.py`) while imports elsewhere reference it in lowercase (`from core.rag_engine import ...`), rename the file to match the lowercase import exactly. This works accidentally on Windows/Mac (case-insensitive filesystems) but will hard-fail on Render's Linux filesystem.
2. **Vector store contamination bug**: The current vector store code likely uses one fixed, shared collection name and a shared persist directory for every video processed. This means different videos'/users' transcript chunks get mixed into the same searchable collection, so RAG chat can return answers pulled from the wrong video. Fix: every vector store must be scoped to a unique identifier (e.g. a job ID) so each processed video gets its own isolated set of vectors, never shared with another.

## Task 2 — Replace local Whisper with Groq API

1. Remove `openai-whisper`, `torch`, `torchaudio` from backend requirements.
2. In the transcription module, keep the existing routing logic (English vs Hinglish) but point the English path at the Groq API (`whisper-large-v3-turbo` model) instead of a locally loaded Whisper model. Read the Groq API key from an environment variable named `GROQ_API_KEY` — add this name to `.env.example`, do not invent or guess a value.
3. Keep the existing Sarvam-based Hinglish transcription path exactly as-is.

## Task 3 — Split into backend (FastAPI) and frontend (Streamlit)

**Backend responsibilities:**
- Expose an endpoint to start processing a video (accepts either a YouTube URL string, or an uploaded audio/video file — support both; the current code only supports a "local file path" input, which doesn't make sense once frontend and backend run on different machines, so it must become a real file upload, not a path string).
- Because a full pipeline run (download → transcribe → summarize → extract → build vector index) can take minutes and Render's request handling isn't built for that, **do not process synchronously inside one request**. Use a background task pattern: the start-processing endpoint returns a job ID immediately; separate endpoints let the frontend poll job status, fetch the finished result once ready, and send chat questions against that job's RAG index.
- Add CORS middleware so the deployed Streamlit frontend's domain is allowed to call this backend. Read the allowed frontend origin from an environment variable (e.g. `FRONTEND_ORIGIN`) rather than hardcoding it or leaving it wide open in production.
- Add a way to explicitly delete/release a finished job's in-memory or database resources once the user is done with it, so resource usage doesn't grow unbounded across many processed videos in one running instance.

**Frontend responsibilities:**
- Never hardcode the backend's URL. Read it from `st.secrets["BACKEND_URL"]`.
- Every HTTP call to the backend must be wrapped in error handling with a generous timeout, so a Render cold start (backend waking up after 15 minutes idle, which can take up to a minute) shows the user a clear "waking up, try again" message instead of crashing the app.
- Replace the current "local file path" text input with a real file upload widget, plus keep the YouTube URL option as an alternative input.
- Implement a polling loop against the job-status endpoint after starting a job, showing progress, until the job is done or errors out.
- Chat feature: send each user question to the backend's chat endpoint for the current job ID, don't try to hold or reconstruct the RAG chain on the frontend side — it lives only on the backend.

## Task 4 — Persistent storage via Neon (Postgres + pgvector)

1. Add a database connection using an environment variable named `DATABASE_URL` (Neon provides this as a connection string) — add the variable name to `.env.example`, do not fabricate a value.
2. Create a `jobs` table (or equivalent) that stores: job ID, status, title, transcript, summary, action items, key decisions, open questions, and timestamps — so a finished job's results survive a Render restart, not just live in process memory.
3. Replace the per-job in-memory/local Chroma vector store with a Postgres + pgvector-backed store, still scoped per job ID (see Task 1's contamination fix — this requirement carries over into the new storage backend, don't reintroduce the same bug).
4. Do not store raw audio files in the database or in any persistent storage — audio should be processed and then discarded, kept only transiently on Render's local (ephemeral) disk during a single job's processing.

## Task 5 — yt-dlp reliability

1. Add support for `yt-dlp` to optionally use a `cookies.txt` file if one is present in a configured path (read the path from an environment variable, e.g. `YT_DLP_COOKIES_PATH`), falling back to no-cookies behavior if the file isn't present. Do not commit any real cookies file to the repository — add `cookies.txt` to `.gitignore`.
2. This is a best-effort mitigation, not a guaranteed fix — leave a code comment noting that YouTube downloads may still intermittently fail from a datacenter IP, and that's expected, not a bug to chase indefinitely.

## Task 6 — Cleanup / hygiene

1. Update `requirements.txt` for backend and frontend separately — backend needs FastAPI/uvicorn/Groq client/etc., frontend needs only Streamlit + requests. Don't leave one bloated combined requirements file.
2. Create `.env.example` listing every environment variable name this project now needs (`MISTRAL_API_KEY`, `SARVAM_API_KEY`, `GROQ_API_KEY`, `DATABASE_URL`, `FRONTEND_ORIGIN`, `YT_DLP_COOKIES_PATH`, etc.) with empty/placeholder values — no real secrets.
3. Confirm `.env` and any cookies file are listed in `.gitignore`.

---

## What Claude Code CANNOT do — these are manual steps for the user

List these clearly at the end of the run, do not attempt them:

1. Creating a free Groq account and generating a `GROQ_API_KEY`.
2. Creating a free Neon project and copying its `DATABASE_URL` connection string.
3. Creating the Render web service (connecting the GitHub repo, setting build/start commands, adding environment variables in Render's dashboard).
4. Creating the Streamlit Community Cloud app (connecting the repo, adding `BACKEND_URL` to its secrets).
5. Exporting `cookies.txt` from a real logged-in YouTube session in a browser (recommend using a secondary/throwaway Google account, not the user's primary one) and uploading/placing it wherever the backend expects it.
6. Filling in real values into the user's actual `.env` file (Claude Code should never do this itself per the hard rules above).

---

## Definition of done

- Codebase is split into a `backend/` and `frontend/` structure (or equivalent), each with its own requirements file.
- No local Whisper/torch dependency remains.
- No synchronous multi-minute processing inside a single HTTP request.
- No shared/contaminated vector collections across jobs.
- No hardcoded URLs or secrets anywhere in code.
- `.env.example` exists and is complete; `.env` is untouched and ignored by git.
- A summary is produced listing what was done automatically vs. what the user must still do by hand.
