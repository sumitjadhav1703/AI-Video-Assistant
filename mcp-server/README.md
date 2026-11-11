# AI Video Assistant MCP Worker

This private Cloudflare Worker exposes four read-only tools over Streamable HTTP at `/mcp`. It reads explicitly shared job records through a restricted Hyperdrive connection.

Use Node 24 and run the following from this directory.

```sh
npm ci
npm run typecheck
npm test
npm run build
```

The build command packages the Worker as a dry run. Follow the [local setup and deployment guide](../docs/mcp-cloudflare/deployment-guide.md) to create a disposable PostgreSQL fixture and run Wrangler on loopback. The [testing plan](../docs/mcp-cloudflare/testing-plan.md) lists the optional integration test environment variables.

The checked-in Wrangler configuration contains placeholders. Hosted configuration and approvals are tracked in the [MCP documentation](../docs/mcp-cloudflare/README.md).
