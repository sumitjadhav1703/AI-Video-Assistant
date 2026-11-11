# Testing plan

## Local acceptance

Run the following in `mcp-server/`.

```sh
npm ci
npm run typecheck
npm test
npm run build
```

Use `TEST_DATABASE_URL` only for a disposable PostgreSQL database named `ava_mcp_test` on loopback with permission to create the test roles and schemas. Run the test suite again with that variable set to exercise the fixture views, explicit content approval, and PostgreSQL grants. The test creates and removes its own fixture objects. Automated local results and hosted acceptance are tracked independently.

For the HTTP suite, start Wrangler with `npm run dev -- --persist-to "$(mktemp -d)"` so previous runs cannot reuse the rate-limit counter. Set `AVA_MCP_TEST_URL=http://127.0.0.1:8787/mcp` and `AVA_MCP_TEST_TOKEN` in the test process. Set `AVA_MCP_TEST_JOB` to the synthetic shared alias when the database has at least two visible shares and the selected job has two chunks at ordinals 0 and 1. Leave it unset and point Wrangler at an unavailable loopback database for the outage check. Run the permission suite separately from the manually seeded Worker because both use the same fixture object names.

| Area | Acceptance checks |
| --- | --- |
| HTTP routing and authentication | Wrong hostname, path, origin, and malformed or missing token fail before database reads. Correct token permits initialize and tools/list. Rate-limited requests produce HTTP 429. |
| MCP compatibility | A Streamable HTTP client initializes, lists exactly four read-only tools, and calls them with the bearer header on every request. Exercise notifications and unsupported methods. |
| Input bounds | Test limit defaults, min/max, malformed aliases and cursors, and cursor reuse for a different video. Invalid requests cannot influence the SQL statement. |
| Pagination | Walk multiple pages with equal timestamps or adjacent ordinals. Verify ordering, unique results, and terminal cursors. |
| Data access | Check eligible metadata, incomplete and failed jobs, hidden and deleted rows, and legacy metadata without content. Verify allowlisted fields and reader privilege denials for production and Preview. |
| Result bounds | Exercise long Unicode text, structured summaries, maximum chunk sizes, and the 24 KiB JSON text limit. Verify timestamp precision on chunk output. |
| Failure handling | Simulate database failure and rate-limit errors. Verify public error payloads and ensure diagnostics avoid credentials, private content, and database internals. |
| Packaging | Verify Worker bundle and binding types. Confirm the named Preview has its own secret, Hyperdrive ID, and rate-limit namespace. |

For manual protocol checks, run the local Worker with synthetic views and launch the pinned Inspector.

```sh
npx --yes @modelcontextprotocol/inspector@2.13.0
```

Select Streamable HTTP, enter the local `/mcp` URL, and supply the bearer header through Inspector. Keep the proxy on loopback. Use synthetic data for manual sessions and omit the token and results from screenshots. [MCP Inspector](https://github.com/modelcontextprotocol/inspector)

## Hosted acceptance

Preview and production remain pending until their respective approvals and account checks. In the synthetic Preview, confirm unauthenticated denial, auth success, discovery, all four tools, role isolation, and stable pagination with fixtures. Verify that a production token fails against Preview and that unexpected hosts or origins fail. Check Cloudflare metrics for CPU, requests, and Hyperdrive usage, and review safe logs for unexpected errors. Once production is authorized, verify its exact hostname and use one approved read-only sample for each tool with the owner client.
