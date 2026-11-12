# AI Video Assistant engineering audit

## Audit 2 — 13 November 2026

**Branch** `audit/engineering-hardening`, cut from `feat/model-fallbacks-hinglish` at `6ac48a2`. All changes are uncommitted for review. Nothing was pushed, deployed, migrated or sent to a live provider.

**Method.** Three read-only reviewers covered the backend pipeline and RAG, the frontend and MCP Worker, and infrastructure, tests and dependencies. Each finding was then confirmed in code before it was fixed. Every bug fix has a regression test, and the main fixes were also run against the original code to show the test fails there. The full system was then exercised end to end:

- real FastAPI, FFmpeg, pgvector and the FlashRank reranker, with mocked provider HTTP only;
- the CI 512 MiB / 0.1 CPU workload gate, run on both the original and the fixed image.

| Area | Result |
| --- | --- |
| Findings | 44 identified; 38 fixed; 1 declined by design; 3 false positives or not reproduced; 2 left open (see [remaining issues](remaining-issues.md)) |
| Critical / high security | None confirmed. Highest open item: per-IP quotas may share one bucket behind Render's proxy (needs a hosted check). |
| Tests | 259 backend (all pass, 0 skipped with disposable pgvector), 15 frontend, 3 MCP Worker + 1 MCP permissions, 8 release-script, 3 browser journeys — all pass |
| Memory (measured) | 512 MiB gate: cgroup peak 465.2 → 425.0 MiB; original image **failed** the gate, fixed image **passes** |
| Dependencies | `langchain`, `langchain-community` (being sunset upstream) and 7 transitive packages removed; 0 known vulnerabilities (pip-audit, npm audit, osv-scanner) |

The most important fixes:

1. **First model call timed out on a cold container.** The gateway charged LiteLLM's first import (about 55 s at 0.1 CPU) against the 60 s generation deadline. This is why the previous AMD64 gate failed at title generation. LiteLLM is now imported in the pre-admission preflight.
2. **One timeout disabled a model route for the rest of the job.** Separately, a route whose 429 cooldown had expired was never used again.
3. **Grounding check accepted trivial quotes.** A one-character quote such as "a" counted as evidence, so an injected instruction could produce a "grounded" answer. Quotes now need at least 4 words and 20 characters (or the whole chunk), matched on word boundaries.
4. **Bad uploads charged the daily quota.** Empty or oversized uploads used up the one-job-per-day allowance before they were rejected.
5. **One blank finding failed a fully paid job.** The blank item was only caught after the model call; it now triggers fallback to the next route instead.
6. **Memory.** A 48 MiB LangChain import used for two regexes and an eager 26 MiB `yt_dlp` import were removed. The LangChain card detector was matched with a local regex, keeping redaction a proven superset.

---

# Previous audit (11–12 November 2026)

**Dates** 11–12 November 2026
**Audit branch** `audit/engineering`
**Source snapshot** `work/project-updates` at `f5841e3` plus its staged, unstaged, and non-ignored untracked work.

The sibling clone matched the source Git diff and file contents across 114 paths before edits. The audit reviewed application source, tests, build and deployment configuration, scripts, workflow, fixtures, documentation, and dependency manifests. Lockfiles and Git history were also checked with tooling. The source checkout is available for comparison.

| Area | Result |
| --- | --- |
| Findings | 17 local findings addressed, including one dependency finding covering 13 advisories. Linux image smoke tests verified the non-root runtime. |
| Security | FFmpeg input formats, provider destinations, validation errors, and browser redirects were hardened. No confirmed critical or high-severity application exploit was found within the exercised scope. |
| Reliability | PostgreSQL job deletion is atomic. Retention cleanup reports partial database failure. MCP aliases round-trip through pagination and lookup. |
| Verification | 191 backend tests, 7 frontend tests, and 4 MCP test definitions passed. Both Chromium journeys and the Vite and Wrangler builds passed. |
| Release | See the [Linux workload results](performance-and-optimization.md#linux-cgroup-v2-release-test) and [hosted checks](remaining-issues.md). |

## Reports

- [Bugs and fixes](bugs-and-fixes.md)
- [Security audit](security-audit.md)
- [Testing report](testing-report.md)
- [Performance and optimization](performance-and-optimization.md)
- [Code simplification](code-simplification.md)
- [Deployment readiness](deployment-readiness.md)
- [Remaining issues](remaining-issues.md)
