# Deployment readiness

| Platform | Local evidence | Remaining check |
| --- | --- | --- |
| Render Free | Blueprint parses. Inference defaults off and auto-deploy is off. Linux ARM64 and AMD64 images built and passed non-root Uvicorn startup, database initialization, and liveness. FFmpeg handled the supported media formats. | Native AMD64 512 MiB workload and verified proxy attribution. |
| Vercel Hobby | Vite production bundle passed. Chromium loaded it on loopback and reached FastAPI across configured origins. | Hosted routing, configured origin, and actual frontend-to-backend traffic. |
| Neon Free | PostgreSQL 16 and pgvector 0.8.1 exercised schema, collection isolation, transaction rollback, deletion, and concurrent reservations. | Hosted endpoint, pooling, role privileges, and free allowance. |
| Cloudflare Workers Free | Wrangler type checking and dry-run bundle passed. Local Streamable HTTP, Hyperdrive fixture, and restricted SQL views passed. | Production Worker CPU, Hyperdrive connection and grants. |

Free-tier assumptions were checked against the platform documentation. [Render Free](https://render.com/docs/free), [Vercel Hobby](https://vercel.com/docs/plans/hobby), [Neon plans](https://neon.com/docs/introduction/plans), [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [Hyperdrive pricing](https://developers.cloudflare.com/hyperdrive/platform/pricing/).

## Linux release gate

**PASS on native Linux ARM64.** The committed image built and passed the strict 512 MiB, zero-swap, 0.1 CPU workload with a 380.83 MiB cgroup peak and zero OOM events.

**AMD64 build and startup passed.** The strict workload failed under Rosetta at title generation after 101.5 seconds. A one-CPU AMD64 diagnostic completed the workload within the 512 MiB cap and peaked at 472.28 MiB. The 450 MiB release threshold was exceeded in that diagnostic. Repeat the strict workload on native AMD64 before relying on it for Render. Render specifies `linux/amd64` for prebuilt images. [Render image requirements](https://render.com/docs/deploying-an-image).

Use the synthetic fixture, image build, disposable database, and workload commands in [Offline workload check](../RECRUITER_DEMO.md#offline-workload-check). See the [measured results](performance-and-optimization.md#linux-cgroup-v2-release-test).

## Legacy deletion state

Stop all workers running the older split-transaction deletion path before enabling the new version. A legacy `deleting` job can be retried with an authorized delete or picked up by the normal retention sweep after it reaches the configured age. The new transaction refuses deletion while a matching reservation is active. Use the documented operator procedure for stale reservations. [Recovery procedure](../ROADMAP_STATUS.md#recovery-after-an-interrupted-process).
