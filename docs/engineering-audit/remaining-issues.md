# Remaining issues and evidence limits

## Audit 2 — 13 November 2026

### Open

- **Per-IP quotas behind Render's proxy (needs a hosted check).**
  - Uvicorn runs without `--forwarded-allow-ips`, so `request.client.host` is probably Render's proxy address.
  - With `JOBS_PER_IP_DAY=1`, the first upload of the day could then block every other visitor.
  - The code deliberately never parses forwarding headers (CLAUDE.md). Do not "fix" this with `FORWARDED_ALLOW_IPS=*`: uvicorn would then trust the leftmost, client-supplied `X-Forwarded-For`.
  - First confirm in Render logs whether clients share one key. Then decide on a trusted-proxy setting.
- **Automatic recovery of a stuck processing slot.** If the worker crashes or is OOM-killed mid-job, the single global slot stays held until an operator runs `python -m backend.recover`. Startup auto-recovery was **declined**: during a Render deploy the old and new instances can overlap, and releasing the slot could run two workers at once. The manual runbook remains the control.
- **The job budget is checked after transcription.** `preflight_processing` runs once the transcript exists. A very dense 10-minute recording can still hit `JobBudgetExceeded` after transcription was paid for. Moving the check earlier needs a token estimate from duration, which is a product trade-off.

### Not verifiable locally

- **Native AMD64** strict gate: the local machine is arm64. CI runs it.
- **Hosted integration:** Render, Vercel, Neon and Cloudflare.
- **Live provider behaviour:** Groq, Gemini, Sarvam and OpenRouter.
- **Retrieval and answer quality** on labelled real media.

### Updated from the previous audit

- **AMD64 "failed at title generation":** root cause found and fixed (B1). The fixed image passes the strict gate on arm64; native AMD64 is still to be confirmed in CI.
- **Unbounded attempt tables:** fixed (B15).

---

# Previous audit (11–12 November 2026)

- **Native AMD64 release gate** — Linux ARM64 passed. Both images built and started. The AMD64 strict workload failed under Rosetta, and the one-CPU diagnostic exceeded the 450 MiB headroom threshold. Native AMD64 performance and OS-package vulnerability scanning remain unverified. See [deployment readiness](deployment-readiness.md).
- **Hosted integration** — Render proxy attribution, Neon pooling and account limits, Vercel-to-Render traffic, Worker CPU and production Hyperdrive grants remain unverified. Local PostgreSQL and Wrangler results cover the exercised contracts.
- **Provider accounts** — Live provider inference, verified free allowances, data-use terms, hosted YouTube acquisition, and optional owner routes remain outside the local audit. Provider results used synthetic HTTP responses.
- **Evaluation** — Citation validation passed with synthetic fixtures. Representative transcription, retrieval relevance and answer-quality evaluation require labelled permissible media and an approved evaluator.
- **Session freshness** — The loaded result is reused when a user returns from the sample view in the same page. A server-side expiry or deletion becomes visible on reload or the next API action.
- **Health endpoint** — The route reports process liveness. A successful post-startup health check alone does not establish current database availability.
