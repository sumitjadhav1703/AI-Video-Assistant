# Deployment report

Filled in by the deployment agent while following [SUBMISSION_GUIDELINES.md](SUBMISSION_GUIDELINES.md). Claude Code reads this file to resume work after deployment.

**Never write secret values here** (keys, tokens, passwords, connection strings). Write variable names, IDs, URLs and results only. Times in UTC.

Status values: ✅ done · ❌ failed · ⏸ stopped (waiting for owner/Claude) · ⏭ skipped (say why).

## Summary

| Field | Value |
|---|---|
| Deployment date (UTC) | |
| Deployed by | Cursor agent (+ owner approvals) |
| DEPLOY_SHA (`origin/main`) | |
| Overall status | |
| Stopped at step (if any) | |
| Live mode | |
| RENDER_URL | |
| VERCEL_URL | |
| MCP Worker URL | |

## Step results

| Step | Status | Time (UTC) | Notes (facts, IDs, check output, no secrets) |
|---|---|---|---|
| 0 Preflight | | | CI run ID: · `.env` names present: |
| 1 Neon | | | project ID: · region: · branch: · database: · owner role name: · `vector` extension: |
| 2 Render | | | service ID: · deploy ID: · `/health`: · `/ready`: · `/demo-mode`: · `/usage`: |
| 3 Vercel | | | project ID: · org/team ID: · deployment ID: · `/eval` `/usage` `/pipeline` codes: |
| 4 CORS | | | `FRONTEND_ORIGIN` set to: · preflight header: |
| 5 Go public | | | `/demo-mode`: · model lists non-empty (generation/embeddings/STT): · smoke upload: · smoke question: · memory peak: |
| 5 Proxy-IP check | | | shared identity across networks? yes / no / not tested |
| 6 Cleanup job | | | secrets set (names): · workflow run ID: · result: |
| 7a MCP DB roles | | | script result: · reader checks: |
| 7b Hyperdrive | | | Hyperdrive ID: · caching disabled: |
| 7c Worker | | | Worker name: · hostname: · version ID: · 401 check: · tools/list: · list_videos: |
| Final checklist F1–F9 | | | |

## Environment variable names set (no values)

| Platform | Names |
|---|---|
| Render | |
| Vercel | |
| GitHub repository secrets | |
| Cloudflare Worker secrets | |
| Hyperdrive | origin user name only: |

## Errors and fixes tried

One row per error. Copy the exact error message with any secret removed.

| Step | Time (UTC) | Error message | Playbook fix tried | Result |
|---|---|---|---|---|
| | | | | |

## Deviations from the guidelines

Anything done differently from SUBMISSION_GUIDELINES.md, and why. "None" if none.

## Open issues for Claude Code

What is unresolved, with the evidence needed to fix it (log excerpts without secrets, step, timestamps).

## Owner notes

Anything the owner observed in the browser (smoke test, look of the pages, cold-start time).
