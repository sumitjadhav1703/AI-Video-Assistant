# AI Video Assistant — Codex Upgrade Planning Brief

See the [current roadmap status](docs/ROADMAP_STATUS.md) for the reconciliation of this brief with the approved hybrid design and the implementation.

> **Purpose:** Give Codex the context and constraints needed to inspect the existing repository and produce a detailed, evidence-based implementation plan for upgrading the AI Video Assistant.
>
> **Important:** This is a **planning-only brief**. Do not implement the features, modify application code, install packages, run migrations, change infrastructure, push commits, or deploy anything during this task. First inspect the repository and return a complete proposed plan for review.

**Repository:** https://github.com/sumitjadhav1703/AI-Video-Assistant

**Primary branch observed:** `main`

**Planning brief date:** 2026-11-05

---

## 1. Instructions to Codex

Act as a senior AI/ML systems engineer and practical cost-conscious software architect. You are reviewing an existing student project, not designing a greenfield enterprise platform.

### Your immediate task

1. Inspect the complete local repository currently open in Codex. Do not rely only on this brief or the README.
2. Check the current Git branch, working tree, uncommitted changes, and recent project structure. Do not overwrite or discard any existing work.
3. Inspect the actual implementation, dependency files, Docker configuration, Render configuration, frontend, database code, and API contracts.
4. Identify which statements in this brief match the code and which are outdated or incomplete.
5. Research current official documentation and current free-tier terms for technologies you recommend. Do not assume that free quotas, model availability, security status, or package versions remain unchanged.
6. Produce a **detailed phased implementation plan**, including architecture, options considered, trade-offs, files likely to change, tests, acceptance criteria, rollback strategy, deployment constraints, and unresolved decisions.
7. Clearly label decisions as **Confirmed**, **Recommended**, **Needs research**, or **Open question**.

### Do not do these things yet

- Do not write or edit application code.
- Do not install dependencies or download models.
- Do not change `render.yaml`, Docker settings, environment variables, billing settings, database schemas, or cloud resources.
- Do not create a LiteLLM Proxy service or another Render service.
- Do not provision a paid resource, start a paid trial, attach a new payment method, or select a paid plan.
- Do not call paid model APIs or consume provider credits during planning.
- Do not run formal DeepEval evaluation yet.
- Do not commit, push, merge, or deploy.

The desired output is a plan for the user to review and approve before implementation begins. If you can create a planning document, propose a filename such as `UPGRADE_IMPLEMENTATION_PLAN.md`, but do not add it to the repository unless the user explicitly asks.

---

## 2. Non-negotiable project constraints

### 2.1 Zero deployment spending is a hard requirement

The project owner is a student and does not want to spend money on deployment, infrastructure, paid add-ons, paid model usage, or surprise billing.

Treat the following as hard constraints, not preferences:

- Keep the existing deployment on free resources wherever technically possible.
- Do not recommend upgrading Render to Starter, Standard, Pro, or any paid plan as the default solution.
- Do not introduce a paid worker, paid database, paid vector database, paid object storage, paid cache, paid monitoring service, paid proxy, or paid model endpoint.
- Do not introduce a new cloud service simply to make the architecture look more advanced.
- Prefer the user's existing MacBook for heavy local development, model experiments, reranking experiments, and offline evaluation.
- Prefer browser-side processing when it provides a measurable benefit and is reliable across supported devices.
- Prefer local/open-source CPU inference for optional model experiments, but do not load heavy models into the constrained Render service.
- Prefer existing Neon PostgreSQL + pgvector over adding another database.
- Use free provider quotas only after verifying the current terms, limits, allowed use, and whether a payment method or automatic paid fallback can cause charges.
- Never describe a service as "free" merely because its library is open source. Model inference, bandwidth, build minutes, storage, and hosted APIs can still cost money.

### 2.2 Prevent accidental charges

Render's official documentation says Free services have included usage limits. Outbound-bandwidth and build-pipeline overages can be billable when a payment method is attached; without a payment method or once a spend limit is reached, Render may suspend services or disable new builds instead. Therefore:

- Inspect current Render workspace usage and billing controls with the user-authorized dashboard if available. Do not change billing settings.
- Report whether the current workspace has a payment method, spend limit, included bandwidth, and build-minute allowance only if this information is actually visible and verified.
- Recommend a conservative spend limit / usage guard where available, but do not configure it without explicit authorization.
- Track outbound data transfer, build usage, provider API usage, and model token usage.
- Avoid sending large media files or large model artifacts through Render unnecessarily.
- Avoid automatic fallbacks to models or providers that may charge after a free quota is exhausted.
- Implement fail-closed behavior for the application's free-only mode: when a verified free quota is unavailable or exhausted, show a clear message instead of silently switching to a potentially paid model.
- Never promise that a provider's free quota is unlimited or permanent.

**Important nuance:** The repository declares a Render Free plan, but the live Render account, actual deployed service plan, current usage, payment-method status, and billing controls have not yet been verified. Do not claim otherwise. Separate repository configuration facts from live account facts.

### 2.3 The project should remain understandable

This is a resume and learning project. The goal is to demonstrate sound engineering decisions and measurable improvements, not to assemble every popular AI framework.

Avoid unnecessary complexity such as:

- A new vector database when pgvector can do the job.
- Elasticsearch/OpenSearch for the initial hybrid-search implementation.
- Celery + Redis unless a concrete requirement proves FastAPI background tasks are insufficient for the demo's needs.
- Kubernetes, microservices, distributed tracing infrastructure, or paid hosted orchestration.
- Agentic RAG, multiple query-rewriting agents, or complex multi-stage retrieval before a baseline demonstrates a need.
- Running a separate LiteLLM Proxy when the existing single FastAPI backend can use the LiteLLM Python SDK.

---

## 3. Existing project — facts to verify against the local code

The public repository currently describes an AI Video Assistant that accepts YouTube URLs or uploaded audio/video, transcribes content, generates meeting/video insights, stores transcript chunks, and answers questions using RAG.

### 3.1 Existing technology stack

- Frontend: React 18 + Vite.
- Frontend hosting: Vercel (per README).
- Backend: Python + FastAPI.
- Backend container: Docker with Python 3.11 slim and FFmpeg installed.
- Backend hosting: Render (per README and `render.yaml`).
- Database: Neon PostgreSQL with pgvector.
- Current generation provider: Mistral through LangChain.
- Current embeddings: Mistral `mistral-embed` through `MistralAIEmbeddings`.
- English STT: Groq Whisper (`whisper-large-v3-turbo` by default).
- Hinglish STT: Sarvam (`saaras:v2.5` by default), translating/transcribing into English.
- Audio download/extraction: `yt-dlp` and FFmpeg.
- RAG orchestration: LangChain LCEL.

### 3.2 Important existing files

Inspect the local versions, not just these descriptions:

| File | Current responsibility to verify |
|---|---|
| `README.md` | Product description, architecture and deployment notes |
| `render.yaml` | Render service plan and environment-variable declarations |
| `Dockerfile` | Python image and FFmpeg installation |
| `.env.example` | Backend configuration variables |
| `backend/api.py` | FastAPI routes, upload handling, CORS, job creation and chat endpoint |
| `backend/jobs.py` | Main processing pipeline and cleanup |
| `backend/db.py` | Neon/PostgreSQL schema and job persistence |
| `backend/core/transcriber.py` | Groq and Sarvam speech-to-text integration |
| `backend/core/summarizer.py` | Title and summary generation |
| `backend/core/extractor.py` | Action items, decisions and open-question extraction |
| `backend/core/vector_store.py` | Transcript chunking, embeddings and PGVector collections |
| `backend/core/rag_engine.py` | Retriever, prompt, LLM and answer generation |
| `backend/utils/audio_processor.py` | YouTube acquisition, FFmpeg conversion, chunking and temp-file cleanup |
| `web/src/api.js` | Frontend-to-backend API calls |
| `web/src/App.jsx` | Frontend flow, job polling and session handling |
| `backend/requirements.txt` | Python dependencies |
| `web/package.json` | JavaScript dependencies |

### 3.3 Existing pipeline to verify

The current intended flow is:

1. User submits a YouTube URL or uploads an audio/video file.
2. FastAPI creates a job and schedules `run_job` as a FastAPI `BackgroundTask`.
3. For uploads, the backend streams the uploaded file to temporary storage. For YouTube URLs, it uses `yt-dlp` on the backend.
4. FFmpeg extracts audio, converts it to mono 16 kHz WAV, and splits it into five-minute chunks.
5. Transcription is performed sequentially using Groq for English or Sarvam for Hinglish.
6. The system generates title, summary, action items, decisions, and open questions.
7. Transcript text is split using `RecursiveCharacterTextSplitter` with the current configuration around 500 characters and 50 characters of overlap.
8. Mistral embeddings are generated and saved into a job-specific PGVector collection.
9. RAG chat uses similarity retrieval, currently with `k=4`, then sends retrieved context to Mistral.
10. Job state and results are stored in Neon. Temporary audio artifacts are deleted.
11. The frontend polls job status and displays the result/chat interface.

The repository currently has per-job vector collection isolation. Preserve job isolation and data cleanup semantics during any redesign.

### 3.4 Current weaknesses or risks to inspect

The previous repository review identified the following items for Codex to confirm:

- RAG appears to use dense vector similarity only; there is no integrated sparse/full-text retrieval or reranker in the current RAG path.
- Transcription currently returns/assembles plain transcript text; segment-level timestamps may not be preserved end-to-end in chunks and RAG metadata.
- Transcription chunk processing appears sequential. Bounded concurrency may help, but must respect provider rate limits and memory.
- `FastAPI BackgroundTasks` executes inside the same application process. It is not a durable independent worker. A restart during a long job may interrupt it.
- The app stores transient files on the service filesystem. Render Free has no persistent disk, and instances can restart.
- Multiple simultaneous video jobs may compete for the same constrained CPU/RAM and provider quotas. Assess a simple concurrency limit.
- The current RAG pipeline rebuilds/loads the vector store on chat requests. Inspect its overhead and opportunities for connection/model reuse.
- Check whether current CORS comments/defaults still match the React/Vite frontend; look for stale references to Streamlit or port 8501.
- Verify whether all environment variables in `.env.example`, Render configuration and actual code agree.
- Confirm upload size limits, request timeouts, FFmpeg subprocess behavior, cleanup on exceptions, and cancellation behavior.
- Check whether API routes other than the admin cleanup endpoint are appropriately protected for the intended demo. Do not introduce a large auth system without a clear need.

Do not assume these are bugs until verified in the local branch.

---

## 4. Target outcome

Upgrade the existing project into a technically credible, low-cost video understanding system that demonstrates:

1. Multi-provider LLM access through a centralized gateway.
2. Advanced RAG with dense + sparse hybrid retrieval, rank fusion, and optional reranking.
3. Timestamp-aware transcript retrieval so answers can reference the relevant point in a video.
4. Less backend media processing and data transfer through client-side preprocessing where beneficial.
5. Better reliability on a constrained free hosting instance.
6. Instrumentation for latency, data size, provider usage and estimated cost.
7. A formal RAG evaluation phase using DeepEval and the user's study material — **only at the end**.

The project should retain its current user-facing purpose and working features. Avoid a full rewrite unless the audit proves it necessary.

---

## 5. Proposed architecture direction

The following is a target to investigate, not a command to implement blindly.

```text
                         USER'S BROWSER / LAPTOP
  +--------------------------------------------------------------+
  | React UI                                                     |
  |                                                              |
  | Optional media preprocessing in a Web Worker:                 |
  | video file -> audio extraction -> compression/normalization   |
  |                                                              |
  | Optional future local AI: browser embedding/STT/reranking     |
  +-----------------------------+--------------------------------+
                                | compressed audio / job request
                                v
                    RENDER FREE FASTAPI BACKEND
  +--------------------------------------------------------------+
  | Job/API orchestration                                        |
  |                                                              |
  | LiteLLM Python SDK + Router (external LLM APIs only)          |
  | Groq/Sarvam STT APIs (subject to verified free quotas)        |
  | Lightweight transcript and retrieval orchestration           |
  | Dense retrieval + PostgreSQL full-text retrieval + RRF       |
  | No heavy local model should be loaded by default              |
  +-----------------------------+--------------------------------+
                                |
                                v
                  NEON POSTGRESQL + PGVECTOR
  +--------------------------------------------------------------+
  | Jobs + transcript chunks + timestamps                        |
  | Vector embeddings                                            |
  | PostgreSQL tsvector / GIN index                               |
  | Per-job isolation and cleanup                                 |
  +--------------------------------------------------------------+

  USER'S MACBOOK (development / optional local mode)
  +--------------------------------------------------------------+
  | Local FastEmbed experiments                                  |
  | Local cross-encoder/reranker experiments                      |
  | Optional browser/device benchmarking                          |
  | DeepEval final-stage offline evaluation                       |
  +--------------------------------------------------------------+
```

### Deployment profiles to consider

Propose how one codebase can support two modes without duplicating the application:

**A. Hosted Free Demo mode**

- Keep Render as a lightweight API/orchestration service.
- No heavy embedding, cross-encoder, Whisper or PyTorch model loaded in the Render process.
- Use existing remote STT and generation APIs only when their free quota has been verified.
- Use Neon/pgvector and PostgreSQL full-text search.
- Use RRF in lightweight application/database code.
- If local reranking is unavailable, provide a clearly configured no-rerank fallback rather than crashing the service.
- Browser audio preprocessing should be optional and fall back to existing upload handling.

**B. Local Development / Research mode**

- Run the backend locally on the user's MacBook.
- Permit optional FastEmbed embeddings and cross-encoder reranking locally.
- Run experiments and benchmarks locally rather than spending Render resources.
- Run DeepEval locally in the final evaluation phase.
- Keep API keys on the backend/local environment, never in browser code.

Assess whether a third optional browser-accelerated mode makes sense for preprocessing, embeddings, or reranking. It must not be required for the app to work.

---

## 6. Feature area A — LiteLLM integration

### Goal

Introduce LiteLLM for a unified interface to two or three LLM providers. The user will select the exact providers later, so the plan must remain provider-agnostic for now.

### Preferred initial direction

Evaluate the **LiteLLM Python SDK + Router inside the existing FastAPI backend**, rather than a separate LiteLLM Proxy deployment.

Why this is the initial preference:

- The project has one backend application.
- The SDK provides a normalized interface and Router features such as retries/fallbacks.
- It avoids another always-on service and another deployment surface.
- It is a better fit for the no-extra-cost constraint.

Official starting point: https://docs.litellm.ai/docs/python_sdk

### Planning requirements

Codex should propose:

- A small provider-independent gateway module, e.g. `backend/core/llm_gateway.py`.
- Model aliases/configuration separated from summarizer, extractor and RAG business logic.
- Async API usage compatible with FastAPI; examine LiteLLM's thread-safety and global-setting guidance.
- A safe retry policy for transient errors, with bounded attempts and backoff.
- Fallbacks only among explicitly approved free-quota providers/models.
- No hidden fallback to a paid model when a free provider is unavailable or quota-limited.
- Provider capability differences (context size, JSON/structured output, streaming, tool use) documented and tested.
- Token usage and provider/model metadata recorded for cost tracking.
- Secret handling through backend environment variables; no keys in React/Vite variables or committed files.
- Mocked tests so normal unit tests do not consume real API credits.

### Security and supply-chain requirement

LiteLLM had a 2026 supply-chain security incident. Before selecting any dependency version, Codex must:

1. Check the current official security page, GitHub advisories, release notes, and package provenance.
2. Confirm the exact current safe release; do not blindly trust a version number in this brief.
3. Never install or use the compromised `1.107.0` artifacts from the October 2026 incident.
4. Pin the reviewed dependency version and keep the lock/requirements reproducible.
5. Avoid floating `latest` container tags or unpinned dependencies for security-sensitive components.
6. Document how the installed package/artifact was verified.

Do not add the LiteLLM Proxy unless the code audit proves the SDK is insufficient and the user explicitly approves the extra deployment/resource implications.

---

## 7. Feature area B — Advanced RAG research and design

The project needs a clear, testable retrieval pipeline — not a stack of unnecessary frameworks.

### 7.1 Baseline first

Before changing retrieval, plan a small baseline capture using the existing RAG implementation:

- Existing embedding model and its dimensions.
- Existing chunking parameters.
- Current top-k.
- Retrieval latency.
- End-to-end chat latency.
- Number of chunks per video.
- Approximate embedding/indexing time.
- Representative questions that test semantic search and exact keyword search.

This is engineering instrumentation, not the final DeepEval stage.

### 7.2 Dense retrieval

Continue to evaluate pgvector for dense vector similarity search.

For embedding model research, compare free/open local candidates such as `BAAI/bge-small-en-v1.5` via FastEmbed with other appropriate small multilingual/English candidates. This is a candidate, not a locked decision.

Model research must compare:

- License and use restrictions.
- Model download size and runtime memory.
- CPU latency on the user's MacBook and, separately, Render Free if considered.
- Embedding dimension and effect on pgvector schema/indexes.
- English/Hinglish/multilingual suitability. The current Sarvam path appears to translate Hinglish to English, but verify actual outputs.
- Quality on representative video transcript questions.
- Whether local embeddings can be used in the hosted demo without moving model inference to Render or creating excessive browser download/compute costs.

Do not assume FastEmbed is safe to load into the current 512 MB Render service just because it is smaller than PyTorch. Benchmark actual peak memory with the whole FastAPI process and FFmpeg dependencies.

If changing embeddings, plan a controlled re-embedding migration. Existing vectors from Mistral embeddings cannot simply be reused with a model that has a different vector space/dimension. Preserve old data until the migration is verified and provide a rollback plan.

### 7.3 Sparse retrieval

Strong initial candidate: PostgreSQL Full-Text Search using `tsvector`, `websearch_to_tsquery` (or an appropriate query parser), and a GIN index.

Reason: PostgreSQL already exists in the architecture. Avoid another search engine unless evidence demonstrates PostgreSQL is insufficient.

Investigate:

- Language/stemming configuration for English transcripts.
- Exact model names, product names, acronyms and technical terms.
- Metadata filters by job/video.
- Indexing and update costs.
- Query behavior for punctuation, timestamps, speaker names and short queries.

### 7.4 Hybrid fusion

Combine dense and sparse result lists. Research Reciprocal Rank Fusion (RRF) as the initial fusion strategy because it can combine rankings without requiring comparable raw vector and keyword scores.

Propose tunable candidate counts, RRF parameters, and job filters. Treat any counts (for example, retrieving 10–20 candidates from each side) as starting values to benchmark, not universal defaults.

### 7.5 Reranking

Evaluate a small local cross-encoder model, potentially through FastEmbed, but do not assume it belongs in Render Free.

Compare:

- Mac-local reranking during development.
- Browser reranking through Transformers.js/ONNX/WebGPU if technically feasible.
- Hosted Free mode with reranking disabled or an explicitly verified lightweight option.

Measure peak memory, first-load/download size, per-query latency, browser compatibility, and retrieval quality. WebGPU is not available in every environment, so provide a fallback or make the feature optional.

Reranking should be applied only to a limited RRF candidate set, then return a configurable final top-k context to the generator. Test whether reranking improves retrieval enough to justify its added latency.

### 7.6 Timestamp-aware transcript chunks

This project is about video, so transcript provenance is important.

Investigate the actual segment/timestamp capabilities and response formats of the selected Groq and Sarvam STT APIs. Preserve, where available:

- `job_id` / video identifier.
- `chunk_index`.
- `start_time` and `end_time` in seconds or milliseconds.
- `speaker` when available and useful.
- `chunk_text`.
- embedding and sparse-search fields.

Group timestamped transcript segments into retrieval chunks without losing the start/end range. If a provider does not return segment timestamps, document the limitation; do not fabricate precise timestamps.

The chat response should eventually be able to cite a video time range and optionally link to the original YouTube video with a timestamp. For uploaded local files, show a timestamp in the UI even if a clickable public video link is unavailable.

### 7.7 Suggested high-level retrieval flow

```text
Question
   |
   +------------------------------+
   |                              |
   v                              v
Dense vector search          Sparse full-text search
   |                              |
   +---------------+--------------+
                   |
                   v
          Reciprocal Rank Fusion
                   |
                   v
          Candidate result set
                   |
                   v
       Optional cross-encoder rerank
                   |
                   v
       Final top-k transcript chunks
                   |
                   v
       LLM answer with timestamps
```

### 7.8 Data model and migration

Review whether continuing per-job PGVector collections is maintainable for hybrid search. Compare:

- Keeping current PGVector collections and adding a compatible sparse index/table.
- Moving to an application-owned `transcript_chunks` table with explicit vector and `tsvector` columns.

A possible conceptual schema (not a command to implement):

| Field | Purpose |
|---|---|
| `id` | Stable chunk identifier |
| `job_id` | Per-video/job isolation |
| `chunk_index` | Source order |
| `chunk_text` | Transcript chunk |
| `embedding` | Dense vector |
| `search_vector` | PostgreSQL full-text vector |
| `start_time` | Start offset |
| `end_time` | End offset |
| `speaker` | Optional speaker label |
| `metadata` | Additional provenance |

Plan indexes, delete behavior, job isolation, migrations, data backfill, and rollback carefully. Do not break the existing job cleanup endpoint or leak chunks across jobs.

---

## 8. Feature area C — Browser-side media preprocessing

### Problem

The current upload route sends the full video file to FastAPI. The backend then uses FFmpeg to extract and normalize audio before transcription. This means large video payloads consume upload bandwidth and backend time even though the RAG pipeline only needs audio/transcript content.

### Proposed experiment

For uploaded local video files only, evaluate client-side video-to-audio extraction using `ffmpeg.wasm` inside a Web Worker:

```text
Browser selects video
        |
        v
Web Worker + ffmpeg.wasm
        |
        v
Extract/normalize/compress audio
        |
        v
Upload audio-only file to FastAPI
        |
        v
Existing STT -> transcript -> RAG pipeline
```

### Requirements and risks

- Keep processing off the browser main thread.
- Show progress, cancellation, errors, and a clear option to use server-side processing.
- Avoid loading the entire media file into a large number of duplicate in-memory buffers.
- Respect browser memory limits and supported codecs.
- Benchmark on representative file sizes and durations, including the user's MacBook and a lower-powered device profile.
- Compare total end-to-end time: browser extraction + upload + backend processing. Do not claim it is faster just because the uploaded file is smaller.
- `ffmpeg.wasm` can be considerably slower than native FFmpeg; make the feature conditional if benchmarks do not show a net win.
- Preserve audio quality sufficiently for transcription; determine a sensible format/sample rate/bitrate based on the STT providers' supported inputs and limits.
- Keep the current backend extraction path as a fallback.
- Do not expose Groq, Sarvam, LiteLLM, or other provider secrets in the browser.

### YouTube input is a separate path

Do not assume ordinary browser `fetch` can reliably extract YouTube media. Cross-origin restrictions and YouTube's delivery behavior differ from an uploaded local file. The README notes that hosted Render/datacenter downloads can face YouTube bot checks.

Keep YouTube URL processing as a separately documented path. Investigate compliant/official approaches and preserve a clear error or upload-audio fallback. Do not add residential proxies or paid bypass services. Do not use browser cookies or other workarounds that compromise account security or violate platform terms.

### Optional future experiment: browser Whisper

Transformers.js/ONNX/WebGPU can run selected speech models in the browser. Treat this as optional research only, not the default transcription design.

Research model size, download cost to the user, WebGPU support, CPU fallback, browser memory, accuracy, multilingual behavior, and performance. Keep the existing Groq/Sarvam path until a local option demonstrates acceptable results. The application must work without WebGPU.

---

## 9. Feature area D — Render Free reliability and runtime safety

### 9.1 Current deployment assumption

The repository's `render.yaml` declares the backend web service as `plan: free`. Official Render compute-plan documentation currently lists Free web services as approximately:

- 0.1 CPU.
- 512 MB RAM.

Free web services can spin down after inactivity, can restart, and do not have persistent disks or multiple instances. Render grants 750 Free instance hours per workspace per calendar month. Confirm current official limits when planning; do not hardcode old facts without checking the docs.

Official sources:

- https://render.com/docs/free
- https://render.com/docs/compute-plans
- https://render.com/docs/faq
- https://render.com/docs/outbound-bandwidth

### 9.2 The zero-cost nuance

Render documentation states that free services still consume included outbound bandwidth and build-pipeline allowances. If these are exceeded and a payment method is attached, overages may be billed. Without a payment method or after a spend limit is reached, Render may suspend services or stop new builds.

This must be treated as a real cost risk. The plan must:

- Minimize large responses and repeated media transfer.
- Avoid serving/downloading large model weights through Render.
- Track outbound bandwidth and build usage.
- Recommend that the user verify billing/spend controls in the Render dashboard.
- Avoid configuring or changing payment methods, spend limits, or service plans without explicit user approval.

### 9.3 Render Free must remain lightweight

Do not load the following into the hosted Free FastAPI process by default:

- Large Whisper/PyTorch models.
- Full Sentence Transformers/PyTorch stacks.
- A local LLM.
- Multiple local embedding and reranker models at once.
- Heavy DeepEval judge models.

Preferred hosted workload:

- FastAPI routing/job orchestration.
- LiteLLM SDK making outbound calls to already-approved external providers.
- Lightweight text transformations.
- PostgreSQL full-text search and pgvector query orchestration.
- RRF ranking logic.
- Provider response parsing and usage tracking.

Any model inference inside Render needs an isolated memory benchmark and a demonstrated need. Do not assume a model is safe for 512 MB based solely on download size.

### 9.4 Job durability

The current `BackgroundTasks` approach is simple but not durable across instance restarts. Plan a minimal, no-new-paid-infrastructure reliability improvement:

- Persist explicit job states and stage checkpoints in Neon.
- Make processing stages idempotent where practical.
- Detect stale `running` jobs after a restart.
- Offer safe retry/resume behavior without duplicating database rows or vector chunks.
- Clean up temporary files after success, failure, and cancellation.
- Limit concurrent heavy jobs on Free (consider one active processing job at a time as an initial safeguard).
- Use bounded concurrency for STT requests only after checking provider rate limits.
- Ensure the UI can distinguish queued, running, interrupted, retryable, completed, and failed states.

Do not add Celery/Redis by default. If Codex believes a separate worker is necessary, explain why it cannot be achieved safely with the current stack and provide a genuinely free alternative. Do not create a paid Render background worker.

### 9.5 Deployment rollback and non-disruption

Plan how to preserve the current working deployment while making incremental changes:

- Keep changes small and independently reversible.
- Avoid database-breaking migrations without a migration/rollback sequence.
- Keep feature flags/config toggles for optional browser processing and local reranking.
- Keep a working fallback path for the current upload/transcription/RAG flow until the new path is proven.
- Run tests and local Docker validation before any deployment.
- The user must explicitly authorize any real deployment.

---

## 10. Feature area E — Instrumentation and performance optimization

Instrumentation should be added early enough to guide engineering decisions, but this is not the formal DeepEval phase.

Collect timings and sizes with minimal overhead:

- Original video/audio size.
- Extracted audio size.
- Browser preprocessing duration (if used).
- Upload duration and bytes transferred.
- Audio conversion duration (server fallback).
- STT duration per chunk and total duration.
- Number of transcript segments and chunks.
- Embedding/indexing duration and number of vectors.
- Dense retrieval duration.
- Sparse retrieval duration.
- RRF duration.
- Reranker duration (when enabled).
- LLM provider/model, token usage, retries and response duration.
- Total time to a usable result.
- Approximate provider cost, with free-quota usage clearly distinguished from paid cost.
- Peak memory and CPU measurements in local and hosted environments where available.

Do not introduce an expensive observability SaaS. Prefer structured logs and a small local benchmark script or CSV/JSON reports.

Investigate:

- Bounded parallel STT calls, respecting API rate limits.
- Combining redundant summary/extraction LLM calls into one schema-validated call where this improves cost/latency without harming output quality.
- Reusing model clients and database connections appropriately.
- Avoiding redundant embeddings and unnecessary vector-store recreation.
- Caching only where cache invalidation and job isolation are correct.
- Limiting context size sent to the LLM after reranking.

No performance improvement should be claimed until measured against a fixed baseline workload.

---

## 11. Final stage only — DeepEval and formal evaluation

**Do not implement or run this phase now.** The user wants evaluation after the system upgrades are complete and will provide a study-material folder named `rag-eval-deepeval-main`.

The supplied Google Drive folder was not accessible in the previous review because the Drive connector was disabled by the workspace administrator and the shared folder could not be inspected. Therefore, the exact study materials and metric definitions remain unknown. Do not claim to have read them.

For now, reserve the evaluation phase and identify what the architecture must expose to support it:

- User question (`input`).
- Generated answer (`actual_output`).
- Retrieved context chunks (`retrieval_context`).
- Expected/reference answer (`expected_output`) where available.
- Expected/reference context or relevant source chunks where available.
- Retrieval rankings and chunk identifiers.
- Provider/model configuration.
- Latency, token usage and estimated cost.
- A versioned evaluation dataset with fixed test questions.

### Candidate evaluation categories to revisit after the user provides the material

**Retrieval quality**

- Precision@K.
- Recall@K.
- MRR.
- NDCG.
- DeepEval Contextual Precision.
- DeepEval Contextual Recall.
- DeepEval Contextual Relevancy.

**Answer quality**

- Faithfulness.
- Answer Relevancy.
- Correctness / answer correctness, using an appropriate reference-based method when reference answers exist.
- Investigate the user's mention of "proximity"; do not guess what this metric means without the study material.

**System performance and cost**

- End-to-end latency and component latency.
- Throughput where meaningful.
- Token usage.
- Estimated API cost and quota usage.
- Upload size and preprocessing time.

Do not conflate ordinary Precision@K/Recall@K with DeepEval's Contextual Precision/Contextual Recall. They have different definitions and data requirements.

DeepEval judge-based metrics may call an LLM and therefore may not be zero-cost. Plan to run evaluations locally and research local/free judges or a small manually reviewed test set. Do not silently use paid judges. The final choice of metrics must be based on the user's supplied study material and the actual evaluation dataset.

Official starting points:

- https://deepeval.com/docs/metrics-introduction
- https://deepeval.com/docs/metrics-faithfulness
- https://deepeval.com/guides/guides-rag-triad
- https://deepeval.com/docs/metrics-ragas

The final evaluation stage should compare at least these system variants if feasible:

1. Existing baseline dense RAG.
2. Hybrid dense + sparse retrieval with RRF.
3. Hybrid retrieval + reranking.

Keep test questions, videos, chunking, and model settings stable during comparisons. Report real results, failure cases, limitations, and uncertainty. Never fabricate scores.

---

## 12. Research standards and technology-selection rules

For every proposed technology, provide:

- Official documentation link.
- License and any usage restrictions.
- Free-tier/quota status as of the research date.
- Whether a payment method is needed.
- Whether overage or automatic billing is possible.
- Local CPU/RAM/storage requirements.
- Hosted Render Free impact.
- Integration complexity and maintenance burden.
- Pros, cons, risks, and a simpler alternative.

Research at least these candidate areas:

1. LiteLLM SDK/Router versus direct provider SDK abstraction.
2. Free model-provider options for chat/generation (provider choices intentionally undecided by the user).
3. FastEmbed and suitable small embedding models versus existing Mistral embeddings.
4. PostgreSQL Full-Text Search + pgvector + RRF versus external search/vector databases.
5. Small cross-encoder reranker options and where they should run.
6. `ffmpeg.wasm` browser preprocessing versus backend native FFmpeg.
7. Optional Transformers.js/WebGPU local inference, with device compatibility fallback.
8. Minimal job reliability approaches compatible with Render Free.
9. DeepEval final-stage metrics based on the user's study material once it is provided.

Use official docs and repository sources first. Use independent technical benchmarks and issue discussions to identify practical failure modes. Distinguish documented facts from estimates and assumptions.

---

## 13. Expected Codex deliverable

Return a detailed plan with these sections:

1. **Executive recommendation** — what should be built and what should not be built.
2. **Repository audit** — current architecture confirmed from actual files, with file paths and any mismatches.
3. **Current bottlenecks** — CPU, RAM, upload size, job durability, STT latency, embedding, retrieval quality, and cost.
4. **Target architecture** — include a Mermaid diagram for Hosted Free Demo and Local Development/Research modes.
5. **Technology decision matrix** — recommended option, alternatives, licensing, free-tier limits, resource requirements, and reasoning.
6. **Phased implementation roadmap** — dependencies between phases and explicit scope boundaries.
7. **Per-phase engineering backlog** — files/modules likely to change, expected behavior, tests, and measurable acceptance criteria.
8. **Database/migration plan** — timestamp metadata, hybrid search schema/indexes, vector migration, job isolation, cleanup and rollback.
9. **Deployment plan** — Render Free constraints, no-cost safeguards, browser/local workload split, and zero-disruption deployment/rollback sequence.
10. **Security plan** — secrets, provider fallback allowlist, LiteLLM supply-chain version verification, upload validation, and endpoint protection appropriate to the demo.
11. **Benchmark plan** — fixed baseline workload and before/after measurements. Do not run DeepEval yet.
12. **Final DeepEval phase placeholder** — exact inputs required and what cannot be finalized until the user supplies `rag-eval-deepeval-main`.
13. **Risks and open questions** — explicitly identify what needs user decisions.
14. **Definition of done** — specific, testable completion criteria.

For each phase, include:

- Objective.
- Why it is needed.
- Proposed approach.
- Files/modules likely affected.
- Dependencies and prerequisites.
- Resource/cost impact.
- Risks and fallback.
- Tests.
- Acceptance criteria.
- Rollback plan.

Make the roadmap incremental. The current app must remain usable throughout implementation.

---

## 14. Initial recommended phase order

Treat this as a starting proposal; revise it if the repository audit finds a better sequence.

| Phase | Focus | Where work should run | Evaluation status |
|---|---|---|---|
| 0 | Read-only repository audit and current baseline | Local machine | Basic timing/size instrumentation only |
| 1 | Reliability guardrails, job checkpoints, concurrency limits | Local first; lightweight Render runtime | No formal DeepEval |
| 2 | LiteLLM SDK integration and 2–3 provider abstraction | Render-compatible lightweight backend | Mocked tests; no paid API test by default |
| 3 | Hybrid RAG: pgvector + PostgreSQL full-text search + RRF | Neon + lightweight backend | Baseline retrieval comparisons, not formal DeepEval |
| 4 | Timestamp-aware transcript segments/chunks and citations | Backend + Neon + frontend | Functional tests |
| 5 | Local embedding model research and controlled vector migration if justified | MacBook first | Benchmark model quality/resources |
| 6 | Optional local/browser cross-encoder reranking | MacBook/browser first; not Render Free by default | Compare retrieval variants |
| 7 | Browser-side audio extraction/preprocessing | User's browser | Measure end-to-end time and payload reduction |
| 8 | Consolidated performance/cost optimization and deployment verification | Local + Render Free | Report measured performance |
| 9 | **Final DeepEval evaluation** | Prefer local/offline | Wait for `rag-eval-deepeval-main` study material |

If a phase depends on another, preserve the dependency. Do not begin model migration before deciding on the embedding model and validating a backup/rollback plan.

---

## 15. Definition of success

The upgraded project should aim to demonstrate the following without increasing deployment spend:

- Multiple LLM providers behind one clean backend interface, with only verified free-quota providers enabled.
- No accidental paid fallback or silent provider billing.
- Hybrid dense + sparse retrieval using the existing PostgreSQL stack.
- RRF and optional reranking with a clearly measured benefit.
- Timestamp-aware transcript retrieval and source references.
- Smaller uploads for supported local video files when browser preprocessing is beneficial.
- The existing Render Free backend remains lightweight and avoids loading heavy local AI models.
- Job failures/restarts are handled more safely, with bounded workload and retry semantics.
- No new paid infrastructure or database is required.
- Measurable reduction in upload bytes, processing time, retrieval latency, or cost — only where experiments prove it.
- A final DeepEval evaluation report based on the user's study material and a fixed test dataset, completed only after all preceding development phases.

**The main engineering achievement is not the number of tools integrated. It is demonstrating a useful, reliable RAG application with measured quality and performance improvements under a strict zero-deployment-spend constraint.**

---

## 16. Reference documentation to verify during planning

These are starting links, not substitutes for checking current docs and changelogs.

### Render

- Free services and limitations: https://render.com/docs/free
- Compute plans: https://render.com/docs/compute-plans
- Outbound bandwidth and overages: https://render.com/docs/outbound-bandwidth
- FAQ / free service behavior: https://render.com/docs/faq

### LiteLLM

- Python SDK: https://docs.litellm.ai/docs/python_sdk
- Getting started: https://docs.litellm.ai/docs/
- Router: https://docs.litellm.ai/docs/routing
- GitHub releases/security: https://github.com/BerriAI/litellm

### PostgreSQL / pgvector / FastEmbed

- pgvector hybrid search: https://github.com/pgvector/pgvector#hybrid-search
- FastEmbed: https://qdrant.github.io/fastembed/
- FastEmbed supported models: https://qdrant.github.io/fastembed/examples/Supported_Models/
- BGE-small model card: https://huggingface.co/BAAI/bge-small-en-v1.5

### Browser processing and local inference

- ffmpeg.wasm overview: https://ffmpegwasm.netlify.app/docs/overview/
- ffmpeg.wasm performance: https://ffmpegwasm.netlify.app/docs/performance/
- Transformers.js: https://huggingface.co/docs/transformers.js
- Transformers.js WebGPU: https://huggingface.co/docs/transformers.js/guides/webgpu

### DeepEval — final phase only

- Metrics introduction: https://deepeval.com/docs/metrics-introduction
- Faithfulness: https://deepeval.com/docs/metrics-faithfulness
- RAG Triad: https://deepeval.com/guides/guides-rag-triad
- RAGAS metrics: https://deepeval.com/docs/metrics-ragas

---

## Final instruction to Codex

**Do a read-only audit and planning exercise only. Produce a rigorous, practical, phased upgrade plan for this exact repository. Preserve the zero-deployment-spend requirement above every other architectural preference. Use Render Free as a hard resource constraint, keep heavy model inference on the user's MacBook or optional browser workers unless benchmarks prove a safe free hosted option, keep DeepEval as the final phase, and do not implement or deploy anything until the user explicitly approves the plan.**
