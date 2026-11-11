# Deployment guide

## Local development

Run commands from `mcp-server/`. Install with `npm ci`. Use the loopback host `127.0.0.1:8787`. Create an ignored `.dev.vars` file with a local-only token. This command creates a new file with restrictive permissions and refuses to replace an existing file.

```sh
node -e 'const fs = require("node:fs"); const crypto = require("node:crypto"); fs.writeFileSync(".dev.vars", "MCP_BEARER_TOKEN=" + crypto.randomBytes(32).toString("base64url") + "\nMCP_HOSTNAME=127.0.0.1:8787\nMCP_ENVIRONMENT=preview\n", { flag: "wx", mode: 0o600 })'
```

For an interactive run, open `psql` as the fixture administrator on a fresh, disposable loopback PostgreSQL database. From `mcp-server/`, run the following in that session. Give the fixture reader a disposable password at the prompt.

```sql
\set ON_ERROR_STOP on
\i tests/fixture.sql
ALTER ROLE ava_mcp_fixture_reader LOGIN;
\password ava_mcp_fixture_reader
INSERT INTO ava_mcp_fixture_base.jobs
  (id, status, step, retrieval_version, created_at, title, summary)
VALUES ('fixture-video', 'done', 'done', 'hybrid-v1', now(), 'Fixture video', 'Synthetic summary.'),
       ('fixture-legacy', 'done', 'done', 'legacy', now(), 'Fixture legacy video', 'Synthetic legacy summary.');
INSERT INTO ava_mcp_fixture_base.shares (job_id, public_id, content_approved)
VALUES ('fixture-video', '00000000-0000-4000-8000-000000000001', true),
       ('fixture-legacy', '00000000-0000-4000-8000-000000000002', true);
INSERT INTO ava_mcp_fixture_base.transcript_chunks
VALUES ('fixture-video', 0, 'Synthetic transcript excerpt.', 0, 1000, 'segment'),
       ('fixture-video', 1, 'Another synthetic excerpt.', NULL, NULL, 'unknown');
```

Set `CLOUDFLARE_HYPERDRIVE_LOCAL_CONNECTION_STRING_HYPERDRIVE` in the local environment to its fixture reader DSN, then start `npm run dev`. Connect MCP Inspector over Streamable HTTP to `http://127.0.0.1:8787/mcp` and add the local token as a bearer header. Read the token from the protected file into the client without printing it. Use the fixture reader login for the Worker connection. Dispose of the local test instance when finished. [Hyperdrive local development](https://developers.cloudflare.com/hyperdrive/configuration/local-development/) · [MCP Inspector](https://github.com/modelcontextprotocol/inspector)

## Proposed production database changes

Use the existing Neon database and confirm the actual schema names, columns, and retrieval version before preparing SQL for approval. The tested [fixture SQL](../../mcp-server/tests/fixture.sql) defines the view contract. For production, use `ava_mcp` and point the views at the verified application tables.

1. Create `ava_mcp.shares` with a unique source job ID referencing `jobs.id ON DELETE CASCADE`, a unique random UUID alias, and `content_approved boolean NOT NULL DEFAULT false`. Keep the table accessible only to the database operator and the view owner. Insert a new UUID when resharing. Review the stored content before approving it.
2. Create the two security-barrier views using the fixture projections and caps. Join against shares for both views. The private view owner needs `USAGE` on the relevant schemas and column-level `SELECT` on only the columns used in the joins, filters, and projections. Remove its schema creation grant after assigning ownership.
3. Create a SQL login named `ava_mcp_reader` with a privately generated password, no elevated role memberships, and `statement_timeout = '2s'`. Grant it database `CONNECT`, schema `USAGE` on `ava_mcp`, and `SELECT` on its two views. Check effective grants inherited from `PUBLIC` and test both successful reads and denied base-table reads and writes as the actual login.
4. If access needs immediate revocation, disable the Worker endpoint, revoke view grants and login, and terminate any remaining reader connections. Remove the two views and share table only after the Worker has stopped using them. Review the rollback with the database owner before applying it.

## Cloud account checks

Before provisioning, verify the account and confirm Workers Free, Hyperdrive headroom, and available Neon Free capacity. Check that the target is `ai-video-assistant-mcp` and that the portfolio Worker is outside the target. Verify the account's selected role and resource scopes. Treat deployment, secret changes, and resource creation as cloud operations. Preview approval and production approval are separate, and applying DDL to live Neon requires its own approval.

## Synthetic Preview

1. After Preview approval, prepare a synthetic PostgreSQL fixture schema named `ava_mcp_preview` and a reader restricted to that schema's views. Create a distinct Hyperdrive configuration with query caching disabled and this reader as its origin identity. Use the direct PostgreSQL endpoint with verified TLS.
2. In the Wrangler `previews` block, use the fixture Hyperdrive ID, a distinct `MCP_RATE_LIMIT` namespace, `MCP_ENVIRONMENT=preview`, and the exact stable Preview hostname in `MCP_HOSTNAME`. The named Preview runs under `ai-video-assistant-mcp`. If Cloudflare first needs to allocate the hostname, keep the placeholder in place so requests fail closed, then redeploy with the confirmed hostname.
3. Run the local checks and create the named Preview. Set the independent Preview token on that Preview with the interactive secret prompt. Check its binding IDs and hostname before the owner smoke test. A returned URL alone leaves data and authentication unverified.
4. Run the hosted checks in the testing plan. Use the stable hostname configured in `MCP_HOSTNAME`.

```sh
npx wrangler preview --name mcp-validation
npx wrangler preview secret put MCP_BEARER_TOKEN --name mcp-validation
```

[Cloudflare Preview setup](https://developers.cloudflare.com/workers/previews/get-started/) · [Preview configuration and secrets](https://developers.cloudflare.com/workers/previews/configuration/) · [Preview isolation](https://developers.cloudflare.com/workers/previews/resources/)

## Production

1. After separate approval for live DDL, review the database ownership, eligibility predicate, backing-table grants, reader grants, and rollback with the database owner. Apply the reviewed proposal under the approved database identity and run read-only checks as the actual reader. Create a distinct production Hyperdrive configuration using the least-privilege login and disable query caching.
2. After production approval, configure the top-level Wrangler bindings and variables with the verified production Hyperdrive ID, rate-limit namespace, `MCP_ENVIRONMENT=production`, and the exact production hostname. Configure the production route and production token for `ai-video-assistant-mcp`. Stage the token with the dashboard or Wrangler versions workflow. Direct `wrangler secret put` can create and deploy a version.
3. Run `npm run build`, review the deployment settings, then run `npx wrangler deploy` using the verified target. Confirm the active deployment and run the bounded owner-client smoke test. Record the version, hostname, route, environment, and outcome without private data or credentials.
4. To contain a bad release, disable the affected route or Preview. For an eligible production rollback, select the prior version for this Worker and verify its hostname, auth policy, secret, and bindings. Rollback leaves connected database resources on their current state.

[Cloudflare Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/) · [Cloudflare rollbacks](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/)
