# Automatic sample deployment

GitHub runs validation on pull requests and pushes to `main`. A passing push to `main` can deploy Render, Vercel, then Cloudflare from the same SHA. Release jobs stop when a target fails or a newer commit supersedes the release. The Actions summary records the last confirmed platform deployment IDs.

Use [PR #4](https://github.com/sumitjadhav1703/AI-Video-Assistant/pull/4) to review the current changes. The prepared frontend sample lives at `/sample` and remains available in sample mode with provider calls disabled.

## One-time setup

Keep the activation variable unset or set to `false` until all targets are configured. Use the designated sample services. Keep inference and paid routes disabled throughout this stage.

1. **GitHub.** Create an Actions environment named `sample-deployment` and restrict it to `main`. Configure the values below in that environment. Require the Validation jobs before merging. For unattended rollout, the sample environment must allow the release job to run without a per-push approval.
2. **Render and Neon.** Use the Git-backed Docker web service `ai-video-assistant-api-sg` in Singapore on the Free plan, tracked on `main`, with Render auto-deploy off and health path `/health`. Point `DATABASE_URL` to the designated Neon Free database with TLS and pgvector available. Set `DEMO_LIVE_MODE=sample` and `ENABLE_PROVIDER_CALLS=false` directly on the service. Keep `ENABLE_PAID_META=false`. Set `FRONTEND_ORIGIN` to the exact Vercel HTTPS origin. Set a random `ADMIN_TOKEN` on the service and store the same token for the cleanup workflow. Check the workspace build, bandwidth and billing settings before enabling automation.
3. **Vercel.** Identify the existing Vite project with Root Directory `web`, build command `npm run build`, output `dist`, and Production Branch `main`. Use its canonical, verified production domain with no redirect. This checkout disables native Git deployment in `web/vercel.json`. The release workflow builds with the public `VITE_BACKEND_URL` set to the verified Render origin. Keep backend secrets out of Vercel project environment variables.
4. **Cloudflare.** Use the dedicated `ai-video-assistant-mcp` Worker and its `workers.dev` hostname. Disable any separate Workers Builds Git trigger for that Worker. Configure a production Hyperdrive binding with a dedicated read-only Neon role. See the [MCP database and Worker setup](mcp-cloudflare/deployment-guide.md). Store a random canonical 32-byte base64url token as `MCP_BEARER_TOKEN` on the Worker and as `MCP_SMOKE_TOKEN` in GitHub. Keep the database password in Hyperdrive.
5. **Retention.** Set GitHub Actions repository secrets `BACKEND_URL` and `ADMIN_TOKEN` for the existing cleanup workflow. The release preflight checks that the cleanup URL is the approved Render URL. The cron runs at 03:00 UTC and removes eligible jobs after 24 hours. Release smoke tests make no cleanup calls.
6. **Activate.** After the native workload and image scan pass and the above settings are verified, set `DEPLOY_SAMPLE_STACK=true` in the GitHub environment. A subsequent passing push to `main` starts the first sample deployment. Confirm the Render deploy ID, Vercel deploy ID, and Cloudflare deploy and version IDs in the Actions summary.

| Environment variables | Purpose |
| --- | --- |
| `DEPLOY_SAMPLE_STACK` | Literal `true` enables deployment after checks. |
| `RENDER_SERVICE_ID`, `RENDER_URL` | Render service ID and canonical HTTPS origin, without a trailing slash. |
| `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`, `VERCEL_URL` | Existing Vercel project and verified production origin. |
| `CLOUDFLARE_ACCOUNT_ID`, `MCP_HOSTNAME`, `MCP_HYPERDRIVE_ID` | Cloudflare account, Worker hostname without a scheme, and production Hyperdrive ID. |

| Environment secrets | Access |
| --- | --- |
| `RENDER_API_KEY` | Read the target service, its sample flags, and deploy status, and trigger a deploy. |
| `VERCEL_TOKEN` | Read and deploy the target Vercel project. |
| `CLOUDFLARE_API_TOKEN` | Deploy and read status for the target Worker. |
| `MCP_SMOKE_TOKEN` | Authenticate the bounded read-only MCP check. |

Store local app values in an ignored `.env`. Store hosted values in each provider's secret settings and the release credentials in the GitHub environment. GitHub Actions reads only its configured values.

## Checks and recovery

The native AMD64 job runs the full backend suite in the built image, performs the 512 MiB workload, and scans that image's OS packages. It uploads build logs, workload JSON and container state, and the full Trivy report. Fixable High or Critical findings fail the gate. Frontend and Worker checks use local fixtures and mocked provider HTTP.

A deployment may stop after a platform has already switched. Use the Actions summary to identify which targets changed. A new passing push to `main` brings all three targets to the same commit. To pause releases, set the activation variable to `false`. If the public sample needs immediate recovery, use each platform's rollback controls with the last known-good IDs. Keep inference off during rollback.

Provider entitlement checks, invited inference, evaluation, and public live access remain separate release stages.
