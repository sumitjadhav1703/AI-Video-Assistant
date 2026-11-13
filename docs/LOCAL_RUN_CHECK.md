# Local run check — 13 November 2026

This check confirms that the branch (the v1 pipeline as evaluated, plus the embedding fallback chain)
builds, starts and works end to end. Everything was local, on free provider routes, with no deploy.

## What is on the branch

- The **v1 RAG pipeline exactly as evaluated** in [evaluation/EVALUATION_REPORT.md](../evaluation/EVALUATION_REPORT.md) (commit `7c9e3f0`).
- **Embedding fallback chain** (`backend/core/embedding_routes.py`):
  - The order in `EMBEDDING_ROUTES_JSON` is now the failover order. For example: Gemini, then
    Cloudflare Qwen, then OpenRouter Nemotron, then NVIDIA Nemotron.
  - Previously a fixed order forced OpenRouter first, so Gemini could never be the primary route.
  - OpenRouter's embedding route always failed. OpenRouter labels `:free` responses
    `private/openrouter/<model>`, so the exact-name check rejected every reply. It now accepts that
    label; any other model is still rejected.
  - On Render, both Nemotron routes stay disabled by code, so production falls back from Gemini to Cloudflare.
- The v2 pipeline work is parked in [future-improvements/v2-rag-pipeline/](../future-improvements/v2-rag-pipeline/README.md). It is not active.

## Results

| Check | Command | Result |
|---|---|---|
| Backend tests, DB tests included | `TEST_DATABASE_URL=<throwaway pgvector> PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s tests` | 260 OK, 0 skipped |
| Evaluation suite | `evaluation/.venv/bin/python -m unittest discover -s evaluation/tests -t .` plus `validate --check` | 46 OK (1 opt-in DB test skipped); 45 goldens valid |
| Web | `npm test`, `npm run build` | 15/15 pass; build OK |
| MCP Worker | `npm run typecheck`, `npm run build` (dry run) | Pass; 1,440 KiB bundle |
| Production image | `docker build -t ai-video-backend:local-check .` | Built (416 MB) |
| Container start, at Render's 512 MiB limit | `docker run --memory 512m ... ai-video-backend:local-check` | `/health` 200, `/ready` 200, `/demo-mode` public |
| Embedding fallback probe | Cloudflare `@cf/qwen/qwen3-embedding-0.6b` via the app's own request and parse code | 200, 1,024 dims (documents and queries) |

## End-to-end journey (real browser, real backend container, throwaway pgvector)

**Input.** A 21-second synthetic clip, created locally with macOS `say` and converted to MP3
(169 KB). It is our own content: a short "project review".

**Steps:**
1. Opened `http://localhost:5173` (Vite dev server proxying to the container on port 8000).
2. Uploaded the clip and pressed **Analyse**.
3. **Processing.** Server-side time to result was **8.1 s**:

   | Stage | Time |
   |---|---|
   | Audio conversion | 0.15 s |
   | Transcription (Groq Whisper) | 2.9 s, 5 segments |
   | Title | 1.0 s |
   | Summary | 1.7 s |
   | Extraction | 1.7 s |
   | Embedding and indexing | 0.6 s |

4. **Result page.** Everything matched the spoken content:
   - Title "Project Review: March 14th Launch".
   - Summary: launch March 14, 12 engineers, $40,000 budget, owners, the dashboard decision, and
     the open mobile question.
   - Action items: Priya owns the database migration; Daniel prepares the release notes by Friday.
   - Key decision and open question both correct.
5. **Chat:**
   - "What is the budget and how many engineers are on the team?" got the answer "$40,000 and 12
     engineers", with a cited source quote and timestamp 0:00–0:20.
   - "Which cloud provider will host the mobile app?" was correctly abstained: "I could not find
     this information in the meeting transcript."
6. **Delete session,** with the confirm dialog. Afterwards the DB had 0 jobs, 0 chunks, 0 vectors and
   0 collections. Provider-attempt history was kept by design.
7. **`/eval`, `/usage`, `/pipeline`** rendered; `/usage` showed live remaining counts that dropped after a job. `/sample` was removed and now serves the home page.

**Resource and cost:**
- Container memory peaked at about **327 MiB of 512 MiB** during the run.
- 8 provider attempts, all on free routes: Gemini Flash ×3, Gemini embeddings ×3, Groq ×1, NVIDIA ×1.
- Paid Meta was forced off. Backend logs held no errors.

## Not covered here

- No deploy to Render, Vercel or Cloudflare. The release workflow only runs from `main`.
- The CI native AMD64 workload gate runs on push; it is not part of this local arm64 check.
