# AI Video Assistant MCP

`ai-video-assistant-mcp` is a private Cloudflare Worker that lets the owner read selected processed-video results through a Streamable HTTP MCP client at `/mcp`. The existing AI Video Assistant pipeline produces the records. The Worker reads approved projections from PostgreSQL through Hyperdrive.

| Document | Covers |
| --- | --- |
| [Architecture](architecture.md) | Request flow, data boundaries, and dependency pins |
| [Tool specification](tools-specification.md) | Tool inputs, pagination, and bounded results |
| [Security and authentication](security-and-authentication.md) | Bearer credentials, database roles, and logging |
| [Deployment guide](deployment-guide.md) | Local setup and separately approved Preview and production steps |
| [Testing plan](testing-plan.md) | Local test matrix and hosted acceptance checks |
| [Cost and limitations](cost-and-limitations.md) | Public Free limits and account-specific verification |

From the repository root, run the local package checks with Node 24.14 and the package lockfile.

```sh
cd mcp-server
npm ci
npm run typecheck
npm test
npm run build
```

Use the deployment guide to configure synthetic data and an owner token for an interactive local session. Hosted testing depends on verified Free account capacity and separate approval for each target.

Local verification passed the TypeScript and Wrangler dry-run build checks, the four-test suite with disposable PostgreSQL, and a Wrangler run that served all four tools through a restricted reader. MCP Inspector called `get_job_status` on the synthetic fixture. Codex CLI compatibility, hosted CPU, Cloudflare account headroom, and live Hyperdrive behavior remain Preview checks.
