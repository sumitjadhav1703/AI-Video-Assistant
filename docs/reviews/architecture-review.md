# Independent architecture review

Reviewed 2026-11-05 against the original local source on `work/project-updates`, before implementation. This is a review report, not evidence that the recommendations are already implemented or deployed.

## Review basis and verdict

Read the complete repository `AGENTS.md` and `AI_VIDEO_ASSISTANT_CODEX_PLANNING_BRIEF.md`, EGM `agents/design_critic.md`, and EGM `resources/document_standards/implementation-readiness-standard.md` from the installed `egm/0.1.0` plugin. Inspected API, jobs, database, every core provider/retrieval module, media processing, frontend API/session lifecycle, dependency and deployment files. Discovered installed web research, code-review-graph, plugin-management and work-state tools; direct source inspection and the web tool were sufficient. No graph embedding or model call was needed.

**Verdict:** Approve a narrowly specified local safety/reliability phase with offline tests. Do not approve live provider enablement, cloud migration, dependency installation for LiteLLM, deployment, or claims of a functioning zero-cost hosted pipeline yet. The brief is a useful requirements document, but it fails the implementation-readiness standard until exact interfaces, schema, failure semantics and acceptance tests are selected for each phase. Its unresolved provider choice must not block input validation or cleanup repairs.

## Priority findings

### Blocker: the existing pipeline has no verified free-only execution path

`backend/core/summarizer.py:10`, `extractor.py:11`, `rag_engine.py:21` and `vector_store.py:24` directly construct Mistral clients. `transcriber.py:39` sends Hinglish audio to Sarvam. Generation, embedding, STT, and provider SDK retries all consume quotas independently. A generation-only allowlist would leave embeddings and STT outside the safety boundary. A model name or environment boolean cannot establish whether the underlying account bills for requests.

**Recommendation:** All outbound inference stays disabled in tests. Define an explicit per-operation provider/model allowlist for generation, embedding and STT; unconfigured operations fail before allocating a processing job. Before any live enablement, verify the selected account tier, exact model availability, quota and billing behavior. Retain the existing adapter behind this gate until provider selection is settled; do not silently substitute or migrate embeddings. Local request budgets provide abuse protection, not a guarantee of provider billing state.

### Blocker: untrusted source handling can read local paths or arbitrary network URLs

`backend/api.py:110` accepts `youtube_url` verbatim. `backend/utils/audio_processor.py:124` treats any HTTP(S) string as a downloadable source and everything else as a local file. A remote caller can submit a filesystem path in the URL form field; it reaches FFmpeg as a local input. The downloader is not restricted to an approved YouTube video URL. This is a real trust-boundary failure; exact exploit impact depends on formats/extractors and was not exercised.

**Recommendation:** Validate and canonicalize the public URL at the API boundary, allowing only supported HTTPS YouTube video forms and a valid video identifier; reject credentials, unexpected ports, playlists and other hosts. Pass explicit source type internally instead of inferring local-vs-remote from a string prefix. Require uploaded files to live in an application-created temporary directory. Disable unsafe remote playlist/protocol behavior. Test local paths, file URLs, localhost/private hosts, deceptive subdomains, credentials, malformed IDs and valid canonical forms without network calls.

### Major: no admission control and no bounded resource budget

`backend/api.py:71` admits every valid submission; `job_chat:154` has no request quota or question size ceiling. Existing upload copying is bounded, but the multipart parser can spool before the route's `file.read()` limit runs. There is no media duration limit, bounded FFmpeg runtime, or download byte limit. `audio_processor.py:102` captures unrestricted FFmpeg output in memory and has no timeout. Short compressed uploads can expand to long PCM streams. CORS is not an abuse or authorization control.

**Recommendation:** One heavy job at a time, no unbounded waiting queue; reject busy submissions with a stable retryable response. Bound total request bytes before multipart parsing, uploaded file size, media duration, conversion deadline, downloader size/duration and provider output tokens. Reject unknown `language` values. Add an application-wide daily admission ceiling in addition to per-client limits. Never rely on arbitrary forwarded IP headers for identity.

### Major: job deletion is not cancellation, and restart recovery is underspecified

`api.py:171` deletes vectors and the job row while `jobs.py:14` can still be running. `web/src/App.jsx:33` initiates deletion on page hide. The running pipeline does not check row deletion, and can later create an orphan vector collection. Progress rows survive restarts, but uploaded source files do not. `db.py:71` updates a step, not a reusable stage checkpoint; all result content is saved only at `finish_job`.

**Recommendation:** For the first patch, refuse deletion of active jobs and stop unloading a processing job as though that cancelled it. Mark expired runs interrupted using an explicit lease/deadline; do not automatically retry provider calls. Honest retry messaging must explain when re-upload is required. Later checkpoint work must persist transcript/output before promising resume. Lease fencing prevents a stale worker from updating a newer attempt, but cannot undo a request already sent to a provider.

### Major: cleanup has failure holes and shared download paths

`api.py:106` removes the upload only for `HTTPException`; write errors and `db.create_job` failure can leak it. In `process_input`, a completed download is added to a local artifacts list, but if conversion throws, `jobs.run_job` never receives that list. `download_youtube_audio` writes by video title in shared `downloades`, allowing collisions. A failed vector build can leave partial data without a finished job.

**Recommendation:** Use one per-job temporary workspace with ownership established before acquisition. Clean it on every exit, including validation, database and subprocess failures. Avoid cleanup by user-controlled paths. Defer vector publishing until an attempt succeeds or delete partial attempt data on failure. Test each failure boundary independently.

### Major: collection isolation is not user authorization

Current UUID job IDs are high-entropy bearer locators; all read, chat and delete operations accept possession of the ID. `api.py:154` can incur repeated inference costs for anyone with that ID. No public enumeration endpoint was found, so this is not evidence of easily guessable IDs.

**Recommendation:** State the intended anonymous demo trust model explicitly. Prefer a separately generated per-job capability token returned once at creation, hashed in the database and required for status/result/chat/delete; keep it in session storage and out of URLs and logs. This avoids a user-account system while allowing public job identifiers. Migration must not silently expose old rows: reject unauthenticated legacy access or provide an explicitly gated legacy path during coordinated rollout. Global budgets remain necessary because anonymous capability creation is itself public.

### Major: API polling reads entire transcripts from Neon

`db.py:114` uses `SELECT *`; `App.jsx:46` polls every three seconds. Status requests fetch transcript and summaries even though the route only returns state. This amplifies database transfer and memory pressure once a job is complete or stores checkpoints.

**Recommendation:** Separate narrow status/existence queries from result reads. Instrument byte sizes and stage durations without transcript text. Remove question/answer logging in `rag_engine.py:67-69` and avoid returning raw provider/database exceptions to browsers.

### Major: phase order delays the schema contract that hybrid retrieval needs

The proposed order puts hybrid search before timestamp provenance. Existing chunks contain only job ID and chunk index; plain-text STT discards timestamps (`transcriber.py:32`). Adding a sparse table without a stable shared chunk identity risks duplicate storage and inconsistent deletion.

**Recommendation:** Specify segment/chunk identity, provenance accuracy and deletion first. Preserve precise times only when returned by STT; otherwise label chunk-level ranges or unknown times. Choose one application-owned chunks table for a future versioned index, with job foreign key and cascading deletion, explicit embedding model/version/dimension, and both sparse/vector fields. Keep legacy collections readable until migration is verified. Do not re-embed historical data in this patch.

## Primary-source feasibility findings

These are public documentation facts checked on the review date, not verified account facts.

| Candidate | Finding | Decision |
|---|---|---|
| Groq | Billing documentation separates Free and paid Developer tiers; upgrade requires a payment method. Exact limits are organization-specific. Published Free Whisper examples show 20 RPM, 2,000 RPD, 7,200 audio-seconds/hour and 28,800/day. | Best candidate to investigate first because the STT dependency already exists. Account tier and exact chosen model still unverified. |
| Mistral | Current subscription docs describe shared included usage across API/Studio/Vibe and optional prepaid pay-as-you-go extension. Public pages do not establish this user's generation or embedding allowance. | Preserve compatibility, but do not label either existing model verified-free. |
| Sarvam | ₹100 signup credit for verified users; requests fail with 402 on exhausted credits. This is finite credit, not an established recurring free quota. | Keep Hinglish path unavailable in strict mode until user-authorized credit policy/account balance is verified. No automatic credit purchase. |
| Gemini | Public pricing includes free access to certain models and indicates free-tier content may be used to improve products. | Optional provider candidate; consent/privacy and project billing tier must be checked before sending meeting transcripts. Do not enable as fallback now. |
| Render | Free services have ephemeral files, idle spin-down and arbitrary restart risk; 750 monthly free instance hours. Bandwidth and build allowances can cause charges or suspension depending on payment/budget settings. | Keep lightweight orchestration only; account spending controls remain unverified. |
| Neon | Pooled endpoints use transaction pooling; session-level advisory locks are unsupported. | Existing database is sufficient for bounded counters and job leases. No Redis needed. |

Sources: [Groq billing](https://console.groq.com/docs/billing-faqs), [Groq rate limits](https://console.groq.com/docs/rate-limits), [Mistral subscriptions](https://docs.mistral.ai/admin/billing-usage/subscriptions), [Sarvam pricing and quotas](https://docs.sarvam.ai/api/getting-started/pricing), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [Render free services](https://render.com/docs/free), [Neon pooling](https://neon.com/docs/connect/connection-pooling).

### LiteLLM incident: brief is substantially correct

The official October 30 report confirms the October 21 malicious `1.107.0` release. The March incident affected `1.82.7` and `1.82.8`; these are distinct incidents. October artifacts passed the project's signing/publishing pipeline, so a valid signature or PyPI hash alone is insufficient evidence of safe content. No currently safe release artifact was selected, installed or independently verified during this review.

Recommendation: retain a small provider-independent boundary using existing dependencies for the immediate phase. Revisit LiteLLM SDK only after exact versions, dependencies, artifact provenance/content and compatibility are reviewed; deny the known affected releases. Router retry/fallback features are unnecessary while providers are unselected. The SDK's open-source licensing does not make its routed APIs free.

Sources: [official October follow-up](https://litellm.vercel.app/blog/security-changes-after-oct-21-2026), [official October attack-chain report](https://litellm.vercel.app/blog/security-incident-oct-21-2026-attack-chain), [project incident issue](https://github.com/BerriAI/litellm/issues/47826), [official March update](https://docs.litellm.ai/blog/security-update-march-2026).

## Minimal robust rate-limit design for Neon and Render

Use database time and short transactions, never a database transaction held open across upload, FFmpeg or provider inference. Avoid session advisory locks through Neon's pooled URL.

1. **Admission budgets:** One small table keyed by `(scope, key, window_start)` with usage and expiry, protected by a primary key. Reserve using a conditional `INSERT ... ON CONFLICT DO UPDATE ... WHERE used + requested <= limit RETURNING ...`. Every required scope must succeed in one transaction; roll back all reservations if any fails. Apply a global cap plus a trusted client/session cap. A fixed window permits a boundary burst; explicitly set a maximum burst and pair it with the active-job gate. Use stricter rolling accounting only if actual provider semantics require it.
2. **Heavy-job slot:** A durable singleton lease row stores owner attempt ID and expiry; an atomic conditional update claims it. Use a short local mutex only to reduce local contention. Reject excess jobs instead of keeping uploaded files in an unbounded background-task queue. Check owner/expiry before every expensive stage and fence all completion writes. Renew while active, set subprocess/provider deadlines, and stop new expensive calls if renewal fails. Expiry alone cannot guarantee an old provider request stopped; do not automatically reclaim and replay unfinished inference as a new job.
3. **Provider budgets:** Before each outbound request, reserve operation units across request, input/output token and audio-duration budgets. Count retries as separate attempts. Reserve the configured output ceiling; reconcile downward only from trustworthy usage responses. Treat timeout/unknown usage conservatively; do not refund an ambiguous request as though it never reached the provider. Distinguish budget denial from provider 429/402 and auth errors. Do not switch providers on quota denial.
4. **Identity and response:** Per-job capability limits protect an existing job; global budgets protect aggregate usage. IP-based limits are supplemental and must use a verified trusted-proxy configuration, with safe global behavior when client attribution is unavailable. Return 429 with bounded `Retry-After` for exhausted application quotas, 503 for unavailable limiter/database, and a stable code the frontend can render. Missing limiter schema/config fails closed for costly endpoints.
5. **Bounded storage and availability:** Enforce a maximum retained set of active windows and opportunistically prune expired rows in limited batches. Anonymous adversaries must not create unlimited distinct keys. Cache only cheap read/status data briefly if needed; do not make every three-second poll mutate a quota row. Database failure blocks new expensive work while `/health` remains independently responsive.

PostgreSQL documents atomic conflict updates and conditional `RETURNING` in [INSERT](https://www.postgresql.org/docs/current/sql-insert.html). The multi-scope transaction, quota reservation and lease choices above are design recommendations, not claims that a provider or Neon supplies these semantics automatically.

Required tests: competing reservations never exceed caps; two admissions yield one owner; denied multi-scope reservation rolls back; process restart retains consumed quota; expired lease cannot finish; absent schema/database blocks inference; ambiguous provider timeout retains reservation; nested SDK retries are disabled or counted; malformed forwarded headers cannot evade the global cap; quota rows remain bounded; no real provider/production database is reached.

## Scope justified now, and explicit later gates

**Implement locally now:** API trust-boundary validation; bounded upload/media execution; comprehensive temporary-file cleanup; one-job admission; bounded chat; explicit free-only configuration validation before work; narrow status queries; sanitized errors/logging; correct React/Vite local CORS/default target; active-deletion protection; offline regression tests and matching documentation. Touch existing API/jobs/db/media/frontend contracts only as required. Preserve existing valid upload and result behavior.

**Implement after one exact design is written:** database-backed durable budgets/leases and per-job capability migration, including schema changes and frontend token flow. These need concurrency SQL tests against a disposable local database before any production acceptance. Adding schema code locally is permitted; running it against Neon is outside current authorization.

**Blocked for live enablement, not for local coding:** account-specific no-cost proof for every STT/generation/embedding operation; exact provider/model selection; actual Render/Neon billing and capacity; safe reviewed dependency artifacts; deployment authorization. No billing dashboard was accessed in this review, no keys or .env contents were read, and no production data was queried.

**Optional experiments:** local FastEmbed/reranker measurements, ffmpeg.wasm browser preprocessing, browser STT/WebGPU, generation-call consolidation and hybrid quality tuning. These are not prerequisites for a safe minimal patch. Keep native FFmpeg as fallback and do not infer speed or memory use from model download size. DeepEval remains final-stage only, pending the user's study material, fixed dataset and explicit judge-cost decision.

Roll back code changes by reverting individual local commits/patches; do not delete retained legacy vector data. Coordinate any future schema/API authentication rollout with frontend release. No performance improvement, live reliability, free-account entitlement or retrieval-quality gain has been measured by this review.

## Review of the orchestrator's selected first slice

The orchestrator subsequently selected these conservative application policy limits: jobs 2/client/day and 10 globally/day; chats 5/client/minute, 20/client/day, 10/job/day and 100 globally/day; one durable processing/chat slot; uploads 25 MB and media 10 minutes; questions 1,000 characters, transcripts 40,000 characters, generation output 1,024 tokens. Provider calls default disabled behind a recorded account attestation; YouTube and Sarvam default disabled. Active deletion returns 409. Reservations are not refunded. Known direct SDK integrations are centralized; LiteLLM remains deferred.

**Conditional approval for local implementation and offline verification.** These are project safety ceilings, not verified provider quotas. The 40,000-character transcript ceiling can still exceed a model's context or per-minute token budget, so provider-specific request budgeting remains a live-enablement gate. A generation gateway alone must not bypass STT or embedding authorization. The selected no-automatic-reclaim slot policy avoids duplicate spending after ambiguous failures, at the cost of requiring an explicit documented local/admin recovery action after crashes. Do not portray that as automatic resume or a durable worker queue.

Client identity is a remaining design obligation: reject spoofable forwarding assumptions, keep the global cap authoritative, and label the current job-ID-as-capability trust model accurately if separate token authentication is deferred. Multipart limits must execute before parsing; disabled provider paths should also reject before writing uploads. Update frontend 409/429/503 error behavior and keep development calls on localhost. Validate quota atomicity in actual disposable PostgreSQL when available; mocked SQL tests alone cannot establish concurrency correctness.
