# Remaining issues and evidence limits

- **Native AMD64 release gate** — Linux ARM64 passed. Both images built and started. The AMD64 strict workload failed under Rosetta, and the one-CPU diagnostic exceeded the 450 MiB headroom threshold. Native AMD64 performance and OS-package vulnerability scanning remain unverified. See [deployment readiness](deployment-readiness.md).
- **Hosted integration** — Render proxy attribution, Neon pooling and account limits, Vercel-to-Render traffic, Worker CPU and production Hyperdrive grants remain unverified. Local PostgreSQL and Wrangler results cover the exercised contracts.
- **Provider accounts** — Live provider inference, verified free allowances, data-use terms, hosted YouTube acquisition, and optional owner routes remain outside the local audit. Provider results used synthetic HTTP responses.
- **Evaluation** — Citation validation passed with synthetic fixtures. Representative transcription, retrieval relevance and answer-quality evaluation require labelled permissible media and an approved evaluator.
- **Session freshness** — The loaded result is reused when a user returns from the sample view in the same page. A server-side expiry or deletion becomes visible on reload or the next API action.
- **Health endpoint** — The route reports process liveness. A successful post-startup health check alone does not establish current database availability.
