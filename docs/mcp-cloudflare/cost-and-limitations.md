# Cost and limitations

The target is Cloudflare Workers Free with Hyperdrive and the existing Neon PostgreSQL data source. Public limits and live account entitlement are separate checks. Account-specific plan, billing status, quota headroom, and resource availability are pending because the account views required sign-in.

| Service | Public limit or plan allowance |
| --- | --- |
| Workers Free | 100,000 requests per day across the account, reset at 00:00 UTC. 10 ms CPU per request and 128 MB memory. [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| Hyperdrive on Workers Free | 100,000 database queries per day, reset at 00:00 UTC. Operations beyond the daily limit fail. [Cloudflare Hyperdrive pricing](https://developers.cloudflare.com/hyperdrive/platform/pricing/) |
| Neon Free | Public pricing lists 100 compute-unit hours per month and 1 GB storage per project. Verify the existing project's specific allowance, usage, and connection budget. [Neon pricing](https://neon.com/pricing) |

Every MCP HTTP interaction contributes to Worker request usage, including initialization and tool discovery. Successful data tool calls also use Hyperdrive. The rate-limit binding controls bursts by Cloudflare location. The platform enforces the account-level daily quotas. If a free quota or database timeout is reached, expect requests to fail until usage is available or the connection recovers.

The Worker offers bounded pagination over existing eligible data. It has zero inference calls, zero media-processing jobs, and zero background state. Client and database latency, including a possible database wake-up, can affect response time. Local runtime tests and a Wrangler dry run do not measure deployed CPU or verify hosted Free quotas. Use the approved synthetic Preview to measure those before considering production.
