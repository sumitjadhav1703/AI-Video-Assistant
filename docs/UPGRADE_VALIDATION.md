# Local safety upgrade validation

Date: 2026-11-05. Branch: `work/project-updates`. Baseline: `f5841e3`.

## Verdict and delivered scope

The planning brief is applicable as a roadmap, with changes described in the implementation plan (removed; read with `git show dfa7e60:UPGRADE_IMPLEMENTATION_PLAN.md`). Its entire architecture is not approved for immediate deployment. The independent EGM design critique conditionally approved the initial safety phase; a separate Sol code reviewer found no blocking issue in that phase after fixes. This was a focused EGM critique, not a claim that every interactive EGM rubric was run.

Implemented locally: durable Postgres admission budgets, token-owned concurrency slots, default-disabled inference, bounded uploads/media/questions/transcripts/output, guarded STT/embeddings/generation, isolated media cleanup, safe active deletion and deletion-failure handling, partial-vector cleanup, narrow status polling, quota feedback, localhost development defaults, pinned tested backend dependencies and patched frontend development tooling. No new cloud service was introduced.

## Verification evidence

| Check | Result |
|---|---|
| Python 3.11 offline suite | 61 tests passed, no skips with local test database enabled |
| Real PostgreSQL 16 | 11 quota/API tests plus collection deletion/cascade test passed in disposable schemas |
| Positive API acceptance | Upload → completed status → result → chat → delete → 404 passed with real local persistence and mocked providers; all usage counters remained consumed |
| Contention | Eight concurrent submissions produced one admitted job; no quota overcount |
| Failure behavior | DB outages, disabled inference and quota denial make no provider calls; upload/provider failures release matching slots |
| Deletion | Active work denied; failed vector deletion preserves prior state; row-delete failure after vector removal marks error |
| Media | Invalid/long/unknown duration rejected; timeout/download failures clean artifacts; local WAV conversion verified |
| Frontend API | Two Node tests passed for 429 retry messaging and 503, with one request per action |
| Frontend build | Vite 6.4.5 production build passed; React plugin 4.7.0 |
| Dependency checks | `uv pip check` passed; `npm audit` reported zero findings including development tools |
| Development proxy | Independently verified `/api/proxy-check` reaches loopback backend as `/proxy-check` |
| Browser | Post-upgrade UI shows 25 MB/10-minute limit; only English/upload options by default; mocked 429 displays 60-second wait and makes one request |
| Whitespace | `git diff --check` passed |

The database tests refuse non-loopback hosts and create/drop uniquely named schemas. No production database or provider account was queried. Tests use mocked provider boundaries; they do not establish transcription/answer quality or real provider compatibility. The existing frontend favicon request returns 404; the mocked quota request intentionally returns 429, with no observed JavaScript crash.

Reproduce the backend checks with Python 3.11:

```sh
python -m pip install -r backend/requirements.lock
python -m unittest discover -s tests -v
# Optional real transaction coverage, only against a disposable local database:
TEST_DATABASE_URL=postgresql://TEST_USER@127.0.0.1:TEST_PORT/TEST_DB python -m unittest discover -s tests -v
```

Without `TEST_DATABASE_URL`, database tests skip explicitly. Frontend: `cd web`, `npm ci`, `npm test`, `npm run build`. Tested locally with Node 24.14.0. A dependency lock records the tested versions; it is not proof that all Python dependency advisories or Linux packaging have been audited.

## Operational limits

- Provider enablement, exact free entitlements, billing/payment methods and Render/Neon usage remain unverified. `ENABLE_PROVIDER_CALLS` is an operator switch, not account verification. No zero-bill guarantee is claimed.
- Application quotas count admitted jobs/chat requests; they are not provider-specific token/audio ledgers. Individual fixed-window IP quotas can be bypassed with IP rotation or shared across campus/NAT users; the global ceiling still applies.
- Reverse-proxy client attribution must be verified before public enablement. Application code never trusts arbitrary forwarding headers.
- Crash reservations remain blocked deliberately. Stop every old worker before manually recovering affected job/slot rows; do not erase usage counters. Automatic resume/replay is not implemented.
- A browser closing does not cancel active work. Active records survive for later release/recovery/cleanup. Job IDs remain bearer secrets.
- YouTube is disabled by default. Optional download socket timeouts do not impose a total wall-clock deadline. No live download or provider request was tested.
- Docker is unavailable on this machine: image build, Linux installation, Render memory headroom and production migration remain unverified. No deployment occurred.
- LiteLLM, multiple provider routing, timestamp citations, hybrid retrieval, embedding migration, reranking, browser preprocessing and DeepEval remain future phases with explicit prerequisites. No retrieval, latency or cost improvement was measured.

## Artifacts

- Reviewed roadmap (removed; read with `git show dfa7e60:UPGRADE_IMPLEMENTATION_PLAN.md`)
- [Independent architecture critique](reviews/architecture-review.md)
- [Backend test output](../output/validation/backend-tests.log)
- [Browser quota denial screenshot](../output/playwright/quota-denial.png)

All application edits are local and uncommitted. The original supplied brief and contributor instructions are preserved. Nothing was pushed, merged or deployed; no cloud resources, billing settings or production schemas were changed.
