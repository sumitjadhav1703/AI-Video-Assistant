# Security and authentication

## Owner token

Generate independent credentials for local development, Preview, and production. Each token encodes 32 random bytes as an unpadded 43-character base64url string. Store it as the `MCP_BEARER_TOKEN` Worker secret and in the owner's client secret store. The request carries `Authorization: Bearer <token>`. For a local-only token, generate and save it directly to the ignored environment file as shown in the deployment guide. Keep authorization values and database credentials out of Git, terminal arguments, screenshots, and diagnostics. [Cloudflare Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/)

`MCP_HOSTNAME` is the exact host and optional port expected for the target. Use a native or proxy-based client with custom header support. The Worker accepts only `POST /mcp` and requires a supplied `Origin` to match the URL origin. It uses a timing-safe comparison for valid bearer token shapes, caps JSON request bodies at 16 KiB, and sets `Cache-Control: no-store`. The `MCP_RATE_LIMIT` binding allows 20 authenticated requests per 60-second period per location and has an independent namespace in Preview. Cloudflare's rate limiting is local to a Cloudflare location and approximate. [Cloudflare Rate Limiting binding](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/)

Rotate a leaked token in the affected target, update the owner client, and verify the old token returns an authentication error. If access must stop immediately, disable the affected route or Preview. Review logs for the affected interval without collecting request content. A Worker version rollback can restore older configuration or credentials, so check the active secret and endpoint policy after rollback. [Cloudflare rollback limitations](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/)

## Database permissions

The production database design uses a dedicated NOLOGIN view owner with access to the required source columns and a separate reader login with schema usage and SELECT on the approved views. Apply the same design to the Preview schema with a separate login and synthetic backing tables. Audit direct grants, role memberships, PUBLIC grants, and executable functions as the actual reader. Check that the reader cannot query base tables, write through views, or see the other environment's data. Review production DDL independently before running it.

Scope row eligibility in PostgreSQL and expose fixed output columns. Treat transcript and summary text as untrusted data in the client. Tool responses may be visible to the client's model provider, history, or diagnostics according to the client's settings.

Keep authorization headers, input arguments, transcript text, summary text, internal job identifiers, connection strings, and raw database errors out of application logs. Keep Cloudflare invocation logging and log retention settings consistent with that policy. Retain only operational signals that are safe for the target.
