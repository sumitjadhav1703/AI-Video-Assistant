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

## One-time production database setup

Use the approved sample Neon database after the backend has initialized `public.jobs` and `public.transcript_chunks`. If the database is new, the app database owner can run `python -c 'from backend.db import init_db; init_db()'` from the audited checkout with the intended Neon connection supplied as `DATABASE_URL` through the shell's protected environment. Verify the database identity before running the command.

Review [the setup SQL](../../mcp-server/setup-production.sql) against the deployed schema. Execute it once from an authenticated `psql` session as the owner of the application tables with permission to create roles. The transaction fails if the production roles or schema already exist. Review an existing installation with the database owner before making changes.

```sql
\i mcp-server/setup-production.sql
\password ava_mcp_reader
ALTER ROLE ava_mcp_reader LOGIN;
```

The view owner has NOLOGIN and column-level access to the required tables. The reader has SELECT on the two security-barrier views. Verify effective permissions as the actual reader, including PUBLIC grants. `SELECT job_id FROM ava_mcp.shared_jobs LIMIT 1` should work on an empty database. A base-table read, view write, and direct read of `ava_mcp.shares` should be denied. Leave the shares table empty until the owner reviews and explicitly approves content. The foreign key removes aliases when the job is deleted.

Create a production Hyperdrive configuration that uses only this reader, the direct Neon endpoint with verified TLS, and query caching disabled. The SQL runs once during platform setup. Repository pushes deploy the Worker against that existing binding.

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

1. Use the dedicated Worker `ai-video-assistant-mcp`. Set up its stable workers.dev hostname `ai-video-assistant-mcp.<account-subdomain>.workers.dev`. The repository workflow manages this workers.dev target. Keep an independent Workers Builds Git deployment disabled so GitHub Actions controls release order.
2. After setting up the reader and Hyperdrive, set `CLOUDFLARE_ACCOUNT_ID`, `MCP_HOSTNAME`, and `MCP_HYPERDRIVE_ID` in the GitHub release environment. Store the Cloudflare deployment API token in the environment's `CLOUDFLARE_API_TOKEN` secret. Use the narrowest available token scope for the target account.
3. Set `MCP_BEARER_TOKEN` on the Worker using Cloudflare's secret store. Add the same value as `MCP_SMOKE_TOKEN` in the GitHub release environment. Use a canonical base64url encoding of 32 random bytes. Confirm the first deployment will retain the secret before enabling the release workflow. Direct Wrangler secret changes can create and deploy a version.
4. The main release workflow deploys the pinned Wrangler package against the supplied binding. It records the active deployment and Worker version and performs a bounded read-only MCP smoke check. Keep the separate synthetic Preview disabled for automated releases.
5. To contain a bad release, disable the affected route. For an eligible rollback, select the prior version for this Worker and verify its hostname, auth policy, secret, and bindings. Rollback leaves connected database resources on their current state. If database access needs immediate revocation, revoke the reader login and grants and terminate its remaining sessions.

[Cloudflare Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/) · [Cloudflare rollbacks](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/)
