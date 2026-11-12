# Bugs and fixes

## Audit 2 — 13 November 2026

Severity reflects user impact on the free demo. "Proven" means the regression test failed on the original code and passes on the fix.

### Backend

| # | Severity | Defect (root cause) | Fix | Verification |
| --- | --- | --- | --- | --- |
| B1 | High | First provider call of a cold process ran LiteLLM's import (≈55 s at 0.1 CPU) inside the 60 s generation deadline; title generation timed out (`llm_gateway.private_litellm` lazily imported) | `api.preflight_pipeline` imports LiteLLM before admission | 512 MiB gate: title stage 58.6 s → 10.6 s; gate FAIL → PASS |
| B2 | High | `llm_gateway.invoke`: a timeout/5xx stored `failed[route]=None` (permanent), and an expired 429 cooldown only set `mixed_failure`, never re-adding the route | Transient failure → 30 s cooldown; expired cooldowns become eligible; auth/4xx stays permanent | `test_transient_route_failure_recovers_after_cooldown_but_auth_failure_does_not` (proven) |
| B3 | High | `Evidence.quote` allowed 1 character and any substring, so "a" grounded any answer; `lower().find()` could mis-slice when case-folding changes length | `rag_engine._locate_quote`: ≥4 words and ≥20 chars (or whole chunk), whole-word `re` match | `test_trivial_or_partial_word_quotes_do_not_ground_answers`, `test_quote_of_a_whole_short_chunk_is_accepted` |
| B4 | Medium | Empty or 25 MB+ uploads were rejected after `db.admit_job`, consuming the 1/day allowance | Check `UploadFile.size` before admission | `test_empty_upload_is_rejected_before_admission`, `test_oversized_upload_is_rejected_before_admission` |
| B5 | Medium | Whitespace-only findings passed the schema, then `_numbered` raised after all paid calls, failing the job without route fallback | `StringConstraints(strip_whitespace, min_length=1)` in `Findings`, so the gateway validator falls back | `test_blank_finding_falls_back_to_next_route_instead_of_failing_job` |
| B6 | Medium | Sync psycopg calls and the ONNX/SHA-256 preflight ran on the event loop in `create_job` and middleware, freezing all requests | `run_in_threadpool` for admission, failure update, slot release and preflight | Full API suite; E2E journey |
| B7 | Medium | 1000-char Devanagari question exceeded the 2048-byte embedding bound; reported as "This session cannot be searched" | 422 "Question is too long" when UTF-8 bytes > `MAX_TEXT_BYTES`; frontend disables Ask | `test_question_over_embedding_byte_limit_is_rejected_before_reservation` |
| B8 | Medium | `PGVector(connection=<url>)` built a new, never-disposed engine per chat/index, without `connect_timeout`/`statement_timeout`, and ran `CREATE EXTENSION` per chat | One cached SQLAlchemy engine (pool 1+1, pre-ping, timeouts), `create_extension=False` | pgvector integration + embedding failover DB tests; E2E |
| B9 | Medium | Meta ASR reserved one audio attempt but sent ⌈duration/30 s⌉ requests | Reserve each piece before sending | `test_meta_asr_sends_parallel_wav_pieces_with_millisecond_turns` (updated) |
| B10 | Low | Segment starting inside the slack window but past the chunk end produced `end > duration`, overlapping the next chunk | Clamp `start` to chunk duration | `test_segment_starting_inside_slack_past_the_chunk_is_clamped` (proven) |
| B11 | Low | Chunker emitted a final chunk with as little as one new character (e.g. length 951 → `[900:951]`) | Fold tails ≤ 50 chars into the previous chunk (max 550) | `ChunkRegressionTests` (proven) |
| B12 | Low | `failed` job result returned HTTP 500 | 409 with the job's message; frontend shows it | `test_failed_job_result_is_a_conflict_not_a_server_error` |
| B13 | Low | `CHATS_PER_IP_DAY` and `MAX_DOWNLOAD_MB` were not capped like other limits | `min(..., 20)` / `min(..., 25)` | `test_chats_per_ip_day_is_capped_like_the_other_limits` (proven) |
| B14 | Low | YouTube CLI download always failed on macOS (`mkdtemp` `/var` vs `realpath` `/private/var`) | `realpath` the directory | Audio processor tests |
| B15 | Low | `provider_attempts` / `audio_attempts` grew forever; per-job cost query had no `job_id` index | `/admin/cleanup` prunes rows older than 7 days (all windows ≤ 24 h / UTC day); indexes on `provider_attempts(job_id)`, `jobs(status, updated_at)` | `AttemptHistoryPruneTests` (DB) |
| B16 | Low | Card numbers next to other digit groups were only redacted because LangChain's detector was also running; the local regex alone missed them | Added the 4×4 card pattern locally before removing LangChain | 15,842-match parity check (0 misses); `GuardrailRegressionTests` |
| B17 | Low | Summary ran a reduce call even for one partial (extra paid call per short job) | Return the single partial | Gateway test; 512 MiB gate: generation calls 15 → 12 |

### Frontend (`web/`)

| # | Defect | Fix |
| --- | --- | --- |
| F1 | Upload shared the 180 s timeout; slow 25 MiB uploads aborted while the job was created server-side | 15 min upload timeout and a "may still be processing" message |
| F2 | Enter during IME composition (Hindi input) sent half-typed questions | `isComposing` / keyCode 229 guard |
| F3 | Drag-and-drop accepted any file type | Extension and MIME check against `ACCEPT` |
| F4 | Invite code cleared before upload succeeded | Kept until success |
| F5 | "Automatic checks have paused." appended repeatedly | Deduplicated |
| F6 | No backoff on 5xx/network errors (~60 requests during a cold start) | Interval doubles to 20 s; resets on success |
| F7 | Unknown status (e.g. legacy `deleting`) polled until the 5-minute deadline | Stops with a clear message |
| F8 | Language and file name lost on reload ("English" shown for Hinglish) | Persisted with the session |
| F9 | Chat errors rendered as normal answers | Error style and `role="alert"` |
| F10 | Results date computed once at module load | Computed at render |
| F11 | `stripMd` removed every `__`, turning `__init__` into `init` | Strips paired markers only; tests added |
| F12 | `Retry-After` on 503 ignored; 204 treated as failure | Both handled |
| F13 | Accessibility: unconfirmed destructive "New session"; hidden nav focusable; no live region for stages; text contrast 1.7–3.7:1; reduced motion ignored | "Delete session" with confirm; `inert`; `aria-live`; tokens ≥ 4.5:1; motion respects preference |

### Tests and tooling

| # | Defect | Fix |
| --- | --- | --- |
| T1 | `web/tests/live-session.browser.mjs` failed on the original code: answer and citation share text, so Playwright's strict locator matched two elements | `.first()`; full journey passes |
| T2 | `tests/browser/journey.mjs` targeted the old button label | Updated for "Delete session" and the confirm dialog |
| T3 | MCP Worker swallowed every error without logging, so a database outage and a code bug looked identical | Logs the error class only (no message, which can contain SQL) |

---

# Previous audit (11–12 November 2026)

| ID | Area | Root cause and impact | Fix and verification |
| --- | --- | --- | --- |
| 1 | API validation | FastAPI returned Pydantic's raw invalid input. A malformed chat request echoed its submitted value. | Keep the `422` detail array with safe field locations, types, and fixed messages. Regression verifies the submitted value is absent and reservation and generation are untouched. |
| 2 | Cleanup authentication | String-mode constant-time comparison raised on non-ASCII headers. | Compare header and configured token as bytes. The malformed-header regression now returns `401` before DB work. |
| 3 | Session deletion | Three separate commits could remove vectors and chunks before a job-row delete failed. A crash could strand the `deleting` state. | Hold the admission lock while removing the collection and row in one transaction. PostgreSQL rolls back all artifacts on a forced constraint violation. Retry, concurrent chat, other-job isolation, legacy cleanup and quota retention are covered. |
| 4 | Scheduled cleanup | The sweep treated all HTTP exceptions as an expected skip and could return success with eligible data left behind. | Continue sweeping after individual failures and return `503` for an incomplete sweep. Busy and concurrently removed jobs remain safe skips. Regression covers all three outcomes in one sweep. |
| 5 | FFmpeg input boundary | FFmpeg could auto-detect a concat manifest disguised as media and open a sibling audio file through its allowed file protocol. | Restrict both probe and decode to supported media demuxers. The synthetic manifest regression fails closed. All ten advertised formats were exercised locally. |
| 6 | YouTube URL boundary | Host validation alone allowed YouTube redirect paths into yt-dlp's generic extractor. | Require a recognized video URL with a canonical ID and use the YouTube extractor and HTTPS download format. Regression covers redirect rejection and canonicalization. |
| 7 | Groq STT transport | SDK defaults allowed an ambient base URL and automatic redirects. | Pin the Groq host and use a transport without redirects or environment proxy settings. Intercepted requests verify host and one wire attempt. |
| 8 | Sarvam STT transport | HTTP redirects could trigger another request carrying the subscription header. | Disable redirects and reject `3xx` responses. Regression verifies no redirect request is sent and no redirect body is accepted. |
| 9 | Transcript redaction | Standalone Groq, NVIDIA, and Google legacy key shapes bypassed the token patterns. | Mask the complete recognized value and preserve character offsets. Synthetic credential and benign-text regressions passed. |
| 10 | Mobile results | Live results missed responsive styles available in the sample. | Share the responsive result rules. At 320 px Chromium verified the Ask button is visible without horizontal scrolling. |
| 11 | Session resume | Resuming a completed result in the same page restarted status and result reads. | Reuse the loaded state. Chromium verifies zero extra reads on resume. Reload and later API actions still check the backend. |
| 12 | Frontend response validation | Malformed successful payloads could reach React with invalid result or citation fields. | Validate result and chat responses before render. Node regression covers malformed `200` payloads. |
| 13 | Frontend redirect handling | Automatic redirect following could replay a custom invite header. | Fail closed on API redirects and keep the backend URL canonical. Node regression checks the fetch option. [Fetch redirect algorithm](https://fetch.spec.whatwg.org/#http-redirect-fetch). |
| 14 | MCP UUID compatibility | PostgreSQL could emit a canonical UUID alias that Zod rejected when passed back as an ID or cursor. | Accept the canonical hexadecimal UUID representation. The regression round-trips an existing alias through real PostgreSQL and MCP pagination. [PostgreSQL UUID](https://www.postgresql.org/docs/16/datatype-uuid.html), [Zod UUID and GUID validators](https://zod.dev/api#uuids). |
| 15 | Python dependency | The pinned filelock had 13 known advisories. The previous LiteLLM pin prevented installing the fixed filelock major. | Upgrade filelock and the compatible LiteLLM LTS patch. The lock resolved, intercepted gateway tests passed, and the advisory scan found zero remaining known vulnerabilities. |
| 16 | Docker security | The build context could include local Worker configuration and dependencies, and the runtime used root for uploaded media processing. | Exclude Worker secret files and all Node dependencies from context. Set a non-root runtime user with writable temporary home. Linux image smoke tests verified UID 65532 and the custom health-check port. |
| 17 | Cleanup workflow | The credentialed cleanup curl command accepted plain HTTP targets and the job inherited default repository token permissions. | Require HTTPS and clear GitHub token permissions. Workflow syntax and security settings checked locally. |

Application severity for this audit is medium for findings 1, 3–9, and 13. Findings 2, 10–12, 14, 16 and 17 are low in the reviewed deployment model. Finding 15 groups upstream advisories whose exploitability in this app was not established.
