# Security audit

## Audit 2 — 13 November 2026

### Secrets

- `gitleaks git` over all 25 commits: 5 hits. All are false positives in tracked files: the SHA-256 hashes in `backend/model_assets/manifest.json` and synthetic strings in `scripts/benchmark_local_embeddings.py` and `tests/test_guardrails.py`.
- `gitleaks dir` also found 10 hits in `.env` and 6 in `output/`. Both are git-ignored, local only, and absent from history. Values were never printed.
- The production frontend bundle contains no keys, tokens or database URLs. A grep match on `__SECRET_INTERNALS` is React's internal name. The only compiled env value is the public `VITE_BACKEND_URL`.
- **No rotation is required by this audit.** Because `output/` evidence files contain secret-like strings, keep that folder out of any upload or share.

### Application

| Finding | Status |
| --- | --- |
| `/docs`, `/redoc` and `/openapi.json` were public in production | Off unless `ENABLE_API_DOCS=true` |
| CORS sent `allow_credentials=True` with wildcard methods and headers, and `FRONTEND_ORIGIN=*` would reflect any origin | Credentials off (bearer tokens, no cookies); explicit methods and headers; `*` ignored |
| `ADMIN_TOKEN` had no minimum length, and a huge `older_than_days` overflowed into a 503 | ≥ 32 characters required; days limited to 0–3650 |
| Grounding accepted 1-character quotes, a prompt-injection path to "cited" answers | See B3 |
| Frontend served without security headers | `vercel.json`: CSP, `nosniff`, `X-Frame-Options DENY`, `Referrer-Policy`, `Permissions-Policy` |
| Rate-limit identity behind Render's proxy | **Open, not changed.** See [remaining issues](remaining-issues.md). |

**Rechecked and holding:**
- SQL is parameterized throughout. The new pruning query uses `psycopg.sql.Identifier`.
- Job access needs an HMAC bearer token bound to the job and expiring after 48 h, compared in constant time.
- Upload paths come from `mkstemp`, so filenames are never trusted.
- FFmpeg runs with protocol and format allowlists.
- `validate_youtube_url` compares exact hosts (credential, port and lookalike-host tricks are rejected), and the API refuses URLs.
- Error bodies use allowlisted messages, and logs contain only exception class names.

**MCP Worker:**
- Constant-time token check.
- 16 KiB body cap; JSON-RPC batches rejected.
- Parameterized SQL through restricted `security_barrier` views.
- Origin and Host pinned.
- Live tests passed locally against Postgres fixtures.

### Tools and dependencies

| Tool | Result |
| --- | --- |
| `bandit -ll` (medium+) | 0 findings. The single initial finding was in this audit's own new code and was fixed before finishing. |
| `pip-audit --strict` (`backend/requirements.lock`) | No known vulnerabilities |
| `npm audit` (web, mcp-server) | 0 vulnerabilities |
| `osv-scanner` (all three lockfiles) | No issues found |
| `ruff --select E9,F` | Clean (4 unused imports fixed) |

**Supply chain:**
- `langchain-community` prints a deprecation warning ("being sunset"). It and `langchain` were removed, which takes `langgraph`, `langgraph-checkpoint`, `langgraph-prebuilt`, `langgraph-sdk`, `langchain-classic`, `httpx-sse` and `ormsgpack` out of the image.
- The lock still has exact pins but no `--hash` entries (pip-audit notes this).
- CI now runs `ruff`, `bandit` and `pip-audit` on every PR, because Trivy scans OS packages only.

---

# Previous audit (11–12 November 2026)

## Credential handling

- Before copying the working snapshot, a redacted pattern scan covered its 73 non-ignored untracked files. The audit also scanned 18 reachable local Git commits and 62 distinct blobs, the current working tree, and all four built Vite artifacts.
- No real secret was confirmed in those inputs. The two initial review matches were the benchmark's disposable DSN guard and the synthetic browser-fixture token. The scan covered provider token shapes, common service tokens, private-key headers, credentialed connection strings, and long secret assignments. It cannot detect every credential format or establish that remote refs and prior clones contain the same history.
- The application keeps job capabilities in authorization headers. API errors omit raw validation input and internal database errors. The built frontend exposes its configured public API URL. Backend and Worker credentials belong in server bindings or local ignored configuration.

## Access, abuse and media

- Job reads, chat and deletion require a job-scoped capability. Owner operations also require the distinct owner credential. Tests cover cross-job attempts, expiry, malformed authorization, inactive jobs, durable limits, and concurrent writes.
- Admin cleanup uses a distinct token. Malformed bytes fail safely. Cleanup no longer signals success after an unexpected delete failure. The workflow uses HTTPS and empty GitHub token permissions.
- FFmpeg probe and decode use media-only demuxers and restricted protocols. Multipart body limits, file caps, duration checks, temp-file cleanup, and DB reservations have local regression coverage. FFmpeg still handles untrusted binary media. The Linux image smoke tests verified the unprivileged runtime UID.
- YouTube is a gated CLI path. Canonical URLs and extractor selection close the generic redirect entry point. Groq and Sarvam transcription requests reject redirects. Live YouTube behavior, proxy attribution and hosted edge protections remain unverified.
- MCP uses a separate bearer secret and a least-privilege view reader. Disposable PostgreSQL checks exercised real grants, shared-record filtering, content approval, and role isolation. Wrangler local tests covered origin rejection, authentication, body caps and rate limiting.
- Redaction is pattern-based. Use of synthetic or public non-personal media remains part of the demo policy.

## Dependencies

| Manifest | Result |
| --- | --- |
| Python lock | 117 pins. Initial `pip-audit` found 13 filelock advisories. Targeted updates from filelock 3.32.7 to 4.2.1 and LiteLLM 1.108.0 to 1.108.5 cleared the known findings on rescan. |
| Frontend lock | npm audit found zero advisories across 116 dependency entries. |
| MCP lock | npm audit found zero advisories across 211 dependency entries. A later repeat hit DNS failure. The lock was unchanged. |
| Docker OS packages | Linux images built. OS-package vulnerability scanning remains pending. |

LiteLLM's updated macOS wheel was inspected for startup hooks before import. Its package initializer and native extension matched the prior pin. The locked pair was exercised with intercepted provider HTTP. Advisory and wheel checks have limited supply-chain coverage. [LiteLLM 1.108.5 LTS](https://github.com/BerriAI/litellm/releases/tag/v1.108.5).

The filelock findings were CVE-2026-112907, CVE-2026-112908, CVE-2026-112909, CVE-2026-112910, CVE-2026-112911, CVE-2026-112912, CVE-2026-112913, CVE-2026-112915, CVE-2026-112935, CVE-2026-112936, CVE-2026-112938, CVE-2026-112939, and CVE-2026-112940.
