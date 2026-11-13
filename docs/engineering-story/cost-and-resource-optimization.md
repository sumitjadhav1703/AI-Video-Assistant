# Cost and resource optimization

Purpose: the cost and resource constraints this project runs under, the choices made because of them, the caps that enforce them in code, and a strict split between money actually spent and numbers that are only estimates.

## Status legend

| Tag | Meaning |
| --- | --- |
| Implemented / Verified | In code on branch `eval/deepeval-framework`; Verified when a test or run artifact confirms it. |
| Not implemented | No code. Listed as an opportunity only, never as a saving. |
| Billed | A cost recorded in the project's own spend ledger. |
| Estimated | Arithmetic on measured numbers or published limits quoted in tracked docs. Shown with its derivation. |
| Not measured | No source. |

---

## 1. Constraints

| Constraint | Detail | Source |
| --- | --- | --- |
| Render Free backend | 512 MiB memory; Blueprint uses `plan: free`, auto-deploy off, inference off by default | [`render.yaml`](../../render.yaml), [ROADMAP_STATUS](../ROADMAP_STATUS.md) |
| Vercel Hobby frontend | Static `web/` build | [RECRUITER_DEMO release order](../RECRUITER_DEMO.md) |
| Neon Free Postgres + pgvector | Autosuspends. Public pricing lists 100 compute-unit hours per month and 1 GB storage per project; the account's actual allowance is unverified | [cost-and-limitations](../mcp-cloudflare/cost-and-limitations.md) |
| Cloudflare Workers Free (MCP worker) | 100,000 requests/day per account, 10 ms CPU and 128 MB per request; Hyperdrive Free 100,000 queries/day | [cost-and-limitations](../mcp-cloudflare/cost-and-limitations.md) |
| No paid Redis, queue or monitoring | Quotas, slots and cooldowns live in Postgres; telemetry is log lines only; jobs run as FastAPI `BackgroundTasks` | [`telemetry.py`](../../backend/core/telemetry.py), UPGRADE_IMPLEMENTATION_PLAN (removed; read with `git show dfa7e60:UPGRADE_IMPLEMENTATION_PLAN.md`) (rejected: Redis, worker, Elasticsearch, separate vector DB) |
| No automatic paid fallback | Paid route is opt-in per request and capped (section 4) | [`audio_budget.py:67-79`](../../backend/core/audio_budget.py), [`provider_budget.py:131-150`](../../backend/core/provider_budget.py) |
| No accidental spending | `ENABLE_PROVIDER_CALLS` defaults to false; every route needs an explicit `verified_free` attestation | [`usage_limits.py`](../../backend/usage_limits.py) |

Free-plan limits for Render, Vercel and Neon are public pricing, not account-verified. [RECRUITER_DEMO release order](../RECRUITER_DEMO.md) lists "verify Vercel Hobby, Render Free bandwidth and build overage protection, Neon Free, and model entitlements" as a pending gate.

---

## 2. Local versus cloud decisions

| Component | Where | Why (source) | Status |
| --- | --- | --- | --- |
| Reranker (FlashRank TinyBERT) | Local, in the backend | Needs no provider quota and no network; about 8 ms p50 per question; process RSS 274,120,704 B in isolation ([BENCHMARK_NOTES](../BENCHMARK_NOTES.md)). Cost: memory on a 512 MiB instance. | Implemented, Verified |
| BM25 | Local, in memory, rebuilt per query | Replaced Postgres FTS (UPGRADE_IMPLEMENTATION_PLAN:3 (removed; read with `git show dfa7e60:UPGRADE_IMPLEMENTATION_PLAN.md`)); about 1 ms p50 | Implemented, Verified |
| Speech to text | Remote free tiers (Groq, Gemini, Sarvam for Hinglish) | Original local Whisper + torch stack was estimated at "~2GB against Render's 512MB free tier" in a code comment, not a measurement (`git show 29eddf7:backend/requirements.txt`, line 3) | Implemented |
| LLM generation | Remote free tiers (Gemini, Groq, OpenRouter `:free`, NVIDIA owner-only) | No local model fits the container. Mistral was dropped because its API needs billing ([HYBRID_IMPLEMENTATION:85](../HYBRID_IMPLEMENTATION.md)) | Implemented |
| Embeddings | Remote free tiers (Gemini, Cloudflare Qwen3; Nemotron routes disabled on Render) | Local BGE-small was measured (326.3 MiB experiment peak RSS, no hosting benchmark) and kept offline | Implemented; local: Experimental |
| Sarvam as default Hinglish route | Rejected as default; gated by `ENABLE_SARVAM` | Finite credit (UPGRADE_IMPLEMENTATION_PLAN:73 (removed; read with `git show dfa7e60:UPGRADE_IMPLEMENTATION_PLAN.md`)) | Implemented (gated) |
| YouTube download | CLI only | YouTube blocks datacenter IPs; proxy and cookie workarounds were rejected on cost and fragility (`git show 3934fa3:README.md`) | CLI only |

---

## 3. Budgets and caps in code

### 3.1 Demo admission, `backend/usage_limits.py:42-48`

Env values can only lower these, never raise them (`min(...)`).

| Cap | Value |
| --- | --- |
| Upload size | 25 MiB |
| Jobs per client IP per day | 1 |
| Jobs globally per day | 5 |
| Chats per IP per minute | 2 |
| Chats per IP per day | 20 |
| Chats per job per day | 3 |
| Chats globally per day | 15 |

Plus one processing slot and one chat slot in Postgres, HMAC-hashed client keys, 48 h job tokens. The planning doc's "2/10" demo limits differ from the code's 1/5; the code wins. Analysis is capped at the first 600 s of media (`audio_processor.py:44`).

### 3.2 Per-job and provider budgets, `backend/core/provider_budget.py`

| Cap | Value | Line |
| --- | --- | --- |
| Provider attempts per job | 24 | `:89` |
| Reserved input tokens per job | 60,000 | `:89` |
| Reserved output tokens per job | 12,000 | `:89` |
| Provider ceilings | strictest of route rpm/tpm/rpd across all operations on the same provider | `:51-74` |
| Reservation | taken before the call, pessimistic, never refunded on ambiguous results | `:1`, `:227-241` |
| Default chat output reservation | 1,024 tokens | `:160` |

Paid route (Meta only, `provider_budget.py:131-150`):

| Cap | Value |
| --- | --- |
| Estimated cost per job | $0.01 |
| Estimated cost per UTC day | $0.05 |
| Paid attempts per job (processing + chat) | 1 |
| Minimum accepted price config | at least $1.25 per million input and $4.25 per million output tokens |

### 3.3 Speech-to-text caps, `backend/core/audio_budget.py:86-112`

Each STT profile has `rpm`, `rpd`, `audio_seconds_hour`, `audio_seconds_day`; usage is counted from the Postgres `audio_attempts` table. Exceeding a day limit returns 86,400 s retry, an hour limit 3,600 s, a minute limit 60 s. Profile values are operator-set and must come from account policy; the repo's example (`HYBRID_IMPLEMENTATION.md:42`) uses rpm 5, rpd 10, 300 s/hour, 600 s/day for Groq.

---

## 4. Paid-route gating (Implemented)

| Gate | Where |
| --- | --- |
| `ENABLE_PROVIDER_CALLS` defaults to false; if true a 32+ character `RATE_LIMIT_SECRET` is required | `usage_limits.py:38-41,51-56` |
| STT profiles: only Meta may be `verified_free: false`; everything else must attest free | `audio_budget.py:52-56` |
| Meta ASR requires `ENABLE_PAID_META=true` and either an owner request or `ENABLE_PUBLIC_PAID_FALLBACK`; it is sorted last in the chain | `audio_budget.py:72-76` |
| OpenRouter routes must be `:free` variants and every request sends `max_price` 0 for prompt, completion and request, with `allow_fallbacks` false | `llm_gateway.py:143-145,236` |
| Paid generation skips routes with `verified_free` false in the forecast; Meta needs explicit owner opt-in (`--allow-paid` or `X-Owner-Allow-Paid: true`) | `provider_budget.py:202-206`, [HYBRID_IMPLEMENTATION:101](../HYBRID_IMPLEMENTATION.md) |
| NVIDIA trial routes: owner-only unless `ENABLE_NVIDIA_PUBLIC`; both Nemotron routes are disabled on Render | `llm_gateway.py:452`, [LOCAL_RUN_CHECK](../LOCAL_RUN_CHECK.md) |
| Evaluation judge (paid Meta) needs `EVAL_ALLOW_PAID_JUDGE=1` and a per-run budget cap | [`evaluation/README.md`](../../evaluation/README.md) |

In the local run check (13 Nov) paid Meta was forced off and all 8 provider attempts used free routes.

---

## 5. Provider quota management (Implemented)

- Every provider call reserves against Postgres under a row lock on `usage_guard` so concurrent workers cannot both spend the last request (`provider_budget.py:77-80,160-177`).
- Rate limit windows: 60 s for rpm and tpm, UTC day for rpd (`:93-105`).
- A 429 stores a per-route cooldown from `Retry-After` (1 s to 86,400 s) in `provider_route_cooldowns`; timeouts and 5xx cool a route for 30 s; auth failures mark the route broken for the job (`llm_gateway.py:186`, `provider_budget.py:108-128`).
- Speech uses its own table, `audio_attempts` (section 3.3).
- A shared provider obeys the lowest configured ceiling across generation and embedding routes (`provider_limits`).
- Audit 2 fix: a transient failure no longer disables a route for the whole job, which avoids needless fallback calls ([perf doc](../engineering-audit/performance-and-optimization.md)).
- During the evaluation Gemini's free daily cap (20 requests) was reached mid-run, which is why four different generators answered ([report §10](../../evaluation/EVALUATION_REPORT.md)).

---

## 6. Upload bandwidth

- The app uploads the raw file (`web/src/api.js:76-83`). The cap is 25 MiB (section 3.1). The client upload timeout was raised to 15 minutes because slow 25 MiB uploads aborted while the job was created server-side ([bugs-and-fixes F1](../engineering-audit/bugs-and-fixes.md)).
- **No bandwidth reduction is claimed.** Browser-side compression was rejected: about 3% fewer bytes on three synthetic files, a 32,232,419-byte GPL core, no real-network test ([BROWSER_MEDIA_EXPERIMENT](../BROWSER_MEDIA_EXPERIMENT.md)).
- Server to Groq: chunks are sent as FLAC, which a code comment puts at about 45% smaller than WAV (`transcriber.py:66`). That saves server egress, not user upload, and has no tracked artifact.
- Render Free bandwidth: not verified (pending gate).

---

## 7. Backend resource reductions (measured)

Audit 2 gate, Linux arm64, 512 MiB, 0.1 CPU, n=1 ([perf doc](../engineering-audit/performance-and-optimization.md)):

| Metric | Original | Fixed |
| --- | --- | --- |
| cgroup peak | 465.2 MiB (gate FAIL) | 425.0 MiB (PASS) |
| Python peak RSS | 408.3 MiB | 374.6 MiB |
| Startup | 22.8 s | 12.9 s |
| Generation calls for 3 jobs | 15 | 12 |
| Image | 1.75 GB | 1.69 GB |
| `import backend.api` RSS (macOS) | 130.3 MiB | 112.3 MiB |

Source changes behind them: removed `langchain.agents` (pii import +47.9 MiB isolated) and `langchain_community`, lazy `yt_dlp` (+26.0 MiB isolated), reranker tokenizer built once, pooled PGVector engine, one fewer summary call for short jobs. The gate threshold is 450 MiB, which leaves 25 MiB under the fixed result. The earlier streaming-ffmpeg change (`0ea372e`) fixed an OOM but has no recorded before-memory.

---

## 8. Caching

**None.** Only an engine cache and a reranker singleton exist; responses are `no-store`. The evaluation's query-embedding cache is evaluation-only. Any saving from caching is an **opportunity, not a result**; repeat rates were never measured.

---

## 9. Token reservation versus actual usage (finding, not fixed)

From [report §5.2 and §8.6](../../evaluation/EVALUATION_REPORT.md) and [usage_measurement.json](../usage_measurement.json):

| | Reserved per chat | Reported per chat |
| --- | --- | --- |
| Input tokens | about 3,440 | about 830 (median) |
| Output tokens | 1,024 | about 150 (median); maximum observed 515 |

Ratio, my arithmetic: 3,440 / 830 is about 4.1x on input and 1,024 / 150 about 6.8x on output; the report says 4-7x. Consequence stated in the report: Gemini's per-minute ceiling is the minimum across its routes, so the embedding route's 30,000 tokens per minute becomes the chat limit, "about 6 chats per minute instead of about 30". Fix proposals (settle reservations to reported usage, cap output near 600) are **Expected** to give about 4x more answers per cap and are not measured. The parked v2 patch contains a settle-to-reported change (item 10) but it was not shipped.

---

## 10. Actual spend versus estimates

### 10.1 Billed (the project's own ledger)

Source: `evaluation/reports/judge_ledger.json` (local, git-ignored; v1 total also in [EVALUATION_REPORT §5.1](../../evaluation/EVALUATION_REPORT.md), v2 total $3.58 in [v2 README](../../future-improvements/v2-rag-pipeline/README.md)). This is the app's ledger of the paid evaluation judge (Meta `muse-spark-1.3`), computed by the project, not a provider invoice; no invoice is in the repo.

| Item | USD | Calls | Note |
| --- | --- | --- | --- |
| Ledger total, all runs | 9.192293 | 2,220 | 8 runs |
| v1 evaluation judge runs (probe, pilot, full, resume 1, resume 2) | 5.6087 | 1,284 | matches [report §5.1](../../evaluation/EVALUATION_REPORT.md) |
| v2 A/B judge runs (3 runs) | 3.583589 | 936 | my sum of the three ledger rows; the v2 README says $3.58 |
| Application provider cost | $0 | n/a | `cost_usd.provider_calls` is 0 in [usage_measurement.json](../usage_measurement.json); every route used is a verified free route |
| Generation and embeddings in the evaluation | $0 | 57 generation attempts, 2 embedding requests | report §5.2 |

The ledger's `budget_usd` values are per-run caps, not spend. The judge is evaluation tooling: no visitor of the app triggers it.

### 10.2 Estimated (derived; not billed)

| Estimate | Derivation | Tag |
| --- | --- | --- |
| Clean rerun of the v1 judge: about $4.90 | 32 x ($0.066 + $0.087) from measured per-question stage costs ([report §5.1](../../evaluation/EVALUATION_REPORT.md)) | Estimated; report labels it a projection |
| Paid-route token profile: about 830 input and 150 output tokens per question attempt, about 1.27 attempts per question | Measured medians and mean, [report §5.2](../../evaluation/EVALUATION_REPORT.md) | Measured inputs; no paid generation price was verified, so **no dollar estimate is given** |
| Maximum paid exposure of the app's Meta route | $0.05 per UTC day by code (`provider_budget.py:148`) | Cap, not spend |
| Maximum demo traffic per day | 5 jobs and 15 chats globally (code) | Cap, not a usage measurement |
| Cloudflare MCP worker daily headroom | 100,000 requests/day, 100,000 Hyperdrive queries/day (public Free limits quoted in the tracked cost doc) | Published limit; actual MCP usage Not measured |

Omitted on purpose: any dollar figure for Render, Vercel, Neon or paid providers' per-token generation, because no tracked doc gives a verified price and measured usage together.

---

## 11. Opportunities (not results)

| Opportunity | Status | Evidence it is worth testing |
| --- | --- | --- |
| Realistic token reservations | Not implemented in v1 (parked in v2) | 4-7x over-reservation, section 9 |
| Cheaper judge: `minimal` reasoning, no pre-rerank stage for routine runs, no `include_reason` | Planned | Output tokens are 61% of judge tokens and about 84% of judge cost (report §5.1) |
| Free offline eval suite in CI | Planned | Costs $0 (report §8.10) |
| Response and embedding caching | Not implemented | No repeat-rate data |

## Sources

- [`backend/usage_limits.py`](../../backend/usage_limits.py), [`backend/core/provider_budget.py`](../../backend/core/provider_budget.py), [`backend/core/audio_budget.py`](../../backend/core/audio_budget.py), [`backend/core/llm_gateway.py`](../../backend/core/llm_gateway.py), [`backend/core/transcriber.py`](../../backend/core/transcriber.py), [`backend/core/telemetry.py`](../../backend/core/telemetry.py)
- [`render.yaml`](../../render.yaml), `UPGRADE_IMPLEMENTATION_PLAN.md` (removed; read with `git show dfa7e60:UPGRADE_IMPLEMENTATION_PLAN.md`)
- [`docs/engineering-audit/performance-and-optimization.md`](../engineering-audit/performance-and-optimization.md), [`docs/engineering-audit/bugs-and-fixes.md`](../engineering-audit/bugs-and-fixes.md)
- [`docs/usage_measurement.json`](../usage_measurement.json), [`docs/LOCAL_RUN_CHECK.md`](../LOCAL_RUN_CHECK.md), [`docs/HYBRID_IMPLEMENTATION.md`](../HYBRID_IMPLEMENTATION.md), [`docs/RECRUITER_DEMO.md`](../RECRUITER_DEMO.md), [`docs/ROADMAP_STATUS.md`](../ROADMAP_STATUS.md), [`docs/BENCHMARK_NOTES.md`](../BENCHMARK_NOTES.md), [`docs/BROWSER_MEDIA_EXPERIMENT.md`](../BROWSER_MEDIA_EXPERIMENT.md)
- [`docs/mcp-cloudflare/cost-and-limitations.md`](../mcp-cloudflare/cost-and-limitations.md)
- [`evaluation/EVALUATION_REPORT.md`](../../evaluation/EVALUATION_REPORT.md), `evaluation/reports/judge_ledger.json` (local, git-ignored; v1 total also in [EVALUATION_REPORT §5.1](../../evaluation/EVALUATION_REPORT.md), v2 total $3.58 in [v2 README](../../future-improvements/v2-rag-pipeline/README.md)), [`evaluation/README.md`](../../evaluation/README.md)
- [`future-improvements/v2-rag-pipeline/README.md`](../../future-improvements/v2-rag-pipeline/README.md)
- Git: `29eddf7` (`DEPLOYMENT_PLAN.md`), `3934fa3` (`README.md`)
