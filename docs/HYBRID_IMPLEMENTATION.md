# Hybrid retrieval implementation and operator guide

New jobs store sanitized timestamped chunks and use stable IDs across PostgreSQL, dense pgvector search, and LangChain BM25. Each branch returns up to ten matches. RRF with constant 60 selects up to twelve candidates for the required TinyBERT cross-encoder. The top four passages go to LangChain for generation and quotation validation. Chat adds citations and retrieval metadata to the existing answer response. Older hybrid indexes retain their original Gemini embedding space. Collections that predate hybrid indexing require reprocessing for hybrid chat.

The server rejects missing model profiles or reranker assets before dispatching the corresponding provider work. It reserves STT requests and audio duration separately from generation and embedding attempts. Requests and uncertain attempts remain charged to application budgets after failures and deletion. A conservative forecast checks the sanitized transcript after STT and before generation or indexing. A recording can meet the upload limit and still exceed the processing budget. The job-wide ceilings are 24 text attempts, 60,000 reserved input units and 12,000 reserved output tokens. UTF-8 byte bounds are conservative reservations. Each provider's configured caps can further restrict admission.

## Local setup

From the repository root, create a Python 3.11 environment with `python3.11 -m venv .venv`. Run `.venv/bin/python -m pip install -r backend/requirements.lock` and `.venv/bin/python scripts/prepare_reranker.py`. The Dockerfile prepares the same verified model during the image build. The [manifest](../backend/model_assets/manifest.json) records the FlashRank ONNX export, source revision, license, attribution, and hashes. Local model binaries are ignored by Git.

Keep `.env` private. `.env.example` starts with providers disabled and empty profiles. A local API also needs a disposable PostgreSQL database with pgvector. The schemas add chunk metadata and accounting tables. They preserve existing job rows and legacy vectors.

For a native backend or CLI with Docker running PostgreSQL, start a loopback-only development database:

```sh
docker run -d --name ai-video-pgvector -p 127.0.0.1:55432:5432 \
  -e POSTGRES_DB=ai_video -e POSTGRES_USER=ai_video \
  -e POSTGRES_PASSWORD=local-dev-only pgvector/pgvector:pg16
docker exec ai-video-pgvector pg_isready -U ai_video -d ai_video
```

Wait for `accepting connections`. In your private `.env`, set `DATABASE_URL=postgresql://ai_video:local-dev-only@127.0.0.1:55432/ai_video`. The example password is only for this disposable loopback database. API startup initializes the schema and enables pgvector. If using the CLI before starting the API, initialize the same schema explicitly from the repository root. [pgvector Docker images](https://github.com/pgvector/pgvector#docker)

```sh
python -c 'from dotenv import load_dotenv; load_dotenv(".env"); from backend.db import init_db; init_db()'
docker exec ai-video-pgvector psql -U ai_video -d ai_video \
  -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

| Setting | Required values after operator verification |
|---|---|
| `STT_PROFILES_JSON` | JSON array with one entry per chosen provider. Each object has `provider`, `model`, `keyenv`, `verified_free`, `rpm`, `rpd`, `audio_seconds_hour`, `audio_seconds_day`. Use `groq` with `GROQ_API_KEY` for English or `sarvam` with `SARVAM_API_KEY` for Hinglish. Each limit is a positive integer from the applicable account policy. |
| `LLM_ROUTES_JSON` | JSON array of explicit routes. Each object has unique `alias`, `tier` (`economy` or `strong`), `provider`, provider-prefixed `model`, `api_key_env`, `verified_free`, `input_limit_tokens`, `rpm`, `tpm`, and `rpd`. Use verified account ceilings. The hosted recruiter demo uses economy. |
| `EMBEDDING_ROUTES_JSON` | Ordered JSON array of unique route objects with `id`, `verified_free`, `rpm`, `tpm`, and `rpd`. Use positive integer limits and set `verified_free` to `true` after checking each account. An explicit `[]` disables embedding routes. |
| Provider calls | `ENABLE_PROVIDER_CALLS=true` requires a stable private `RATE_LIMIT_SECRET` of at least 32 characters. Enable it only after verifying free entitlements and privacy terms for each operation. For browser tests on a loopback API, also set `DEMO_LIVE_MODE=invited`, a private `DEMO_INVITE_CODE` and a distinct `JOB_TOKEN_SECRET`. Generate secrets with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. |

### Groq transcription and generation

Set `GROQ_API_KEY` privately and confirm Free plan access to both exact models in the Groq console. Configure each operation independently. The following are example application ceilings for a small local check. Lower them for a smaller verified allowance or shared usage. Keep the generation request cap within the daily token allowance using `rpd × tpm` as a conservative upper bound. The app reserves generation input by UTF-8 bytes and includes the output ceiling. Its processing forecast can reject a Groq-only job at the free TPM cap even when the media fits the upload limits. Keep the verified cap if that happens. [Groq account rate limits](https://console.groq.com/settings/limits) · [Groq rate limit documentation](https://console.groq.com/docs/rate-limits)

```dotenv
STT_PROFILES_JSON=[{"provider":"groq","model":"whisper-large-v3-turbo","keyenv":"GROQ_API_KEY","verified_free":true,"rpm":5,"rpd":10,"audio_seconds_hour":300,"audio_seconds_day":600}]
LLM_ROUTES_JSON=[{"alias":"groq-economy","tier":"economy","provider":"groq","model":"groq/openai/gpt-oss-20b","api_key_env":"GROQ_API_KEY","verified_free":true,"input_limit_tokens":16384,"rpm":20,"tpm":8000,"rpd":20}]
```

### Embedding routes

Include eligible routes in this order. Omit any route whose account, model, or data terms you cannot verify.

| `id` | Model and dimensions | Environment variables |
|---|---|---|
| `openrouter-nemotron` | [`nvidia/nemotron-3-embed-1b:free`](https://openrouter.ai/nvidia/nemotron-3-embed-1b:free?view=api), 2,048 | `OPENROUTER_API_KEY`, local internal evaluation |
| `cloudflare-qwen` | [`@cf/qwen/qwen3-embedding-0.6b`](https://developers.cloudflare.com/workers-ai/models/qwen3-embedding-0.6b/), 1,024 | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_WORKERS_AI_TOKEN` |
| `gemini-embeddings` | [`gemini-embedding-001`](https://ai.google.dev/gemini-api/docs/embeddings), 768 | `GEMINI_API_KEY` |
| `nvidia-nemotron` | `nvidia/nemotron-3.5-embed-1b`, 2,048 | `NVIDIA_API_KEY`, local synthetic owner evaluation only |

Both Nemotron endpoints are subject to NVIDIA trial terms, including the model accessed through OpenRouter. Use them for private internal evaluation with synthetic inputs. The backend excludes them on Render. Configure Cloudflare or Gemini for hosted inference after the live release gates pass. [OpenRouter model terms](https://openrouter.ai/nvidia/nemotron-3-embed-1b:free?view=api) · [NVIDIA trial terms](https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf)

Check current limits in each account before setting positive `rpm`, `tpm`, and `rpd` caps. For quotas expressed in other units, such as Cloudflare neurons per day, set application ceilings that fit the verified allowance across the account's usage. Remove `EMBEDDING_ROUTES_JSON` entirely to use the legacy Gemini settings (`ENABLE_GEMINI_EMBEDDINGS=true`, `GEMINI_EMBEDDINGS_VERIFIED_FREE=true`, positive `GEMINI_EMBEDDINGS_RPM`, `_TPM`, `_RPD`, and `GEMINI_API_KEY`). A provider shared by generation and embeddings obeys the lowest configured ceiling. [OpenRouter limits](https://openrouter.ai/docs/api/reference/limits) · [Cloudflare Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) · [Gemini limits](https://ai.google.dev/gemini-api/docs/rate-limits)

For example, a local test with only an eligible OpenRouter key can use the following shape and conservative application ceilings. Adjust the limits to your verified allowance.

```dotenv
EMBEDDING_ROUTES_JSON=[{"id":"openrouter-nemotron","verified_free":true,"rpm":10,"tpm":12000,"rpd":10}]
```

Indexing can try the next eligible route after a quota or availability failure. A fallback re-embeds the entire job in one vector space before publishing the index. An indexed job pins its route and dimension. Chat embeds queries in that same space. Keep the original route enabled to query those jobs, or submit a new job to rebuild the index in a different space.

For Cloudflare, open Workers AI → Use REST API in the dashboard. Copy the Account ID and use the Workers AI API token template for that account. Store both values in the corresponding variables from the table. [Cloudflare REST API setup](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)

`verified_free` records an operator attestation. Before enabling `ENABLE_PROVIDER_CALLS`, verify that each key belongs to an account or project with the required free model access, that overage and auto top-up cannot incur charges, and that the retention and data-use terms permit your inputs. OpenRouter's exact free model excludes confidential and personal input. For Cloudflare verify Free plan enforcement and scope the token to Workers AI for the chosen account. For Gemini verify the project's billing tier and data terms. Use synthetic or permitted non-personal material. STT receives original audio, and embedding providers receive sanitized chunks and queries. Text redaction preserves names and can miss sensitive data. [OpenRouter model terms](https://openrouter.ai/nvidia/nemotron-3-embed-1b:free) · [Cloudflare data usage](https://developers.cloudflare.com/workers-ai/platform/data-usage/) · [Gemini terms](https://ai.google.dev/gemini-api/terms)

## Provider and release gates

Configure the economy routes below after verifying the corresponding account, model, and terms. The gateway sets the order independently of the JSON array order.

| Order | `provider` | `model` | `api_key_env` |
|---|---|---|---|
| 1 | `groq` | `groq/openai/gpt-oss-20b` | `GROQ_API_KEY` |
| 2 | `nvidia_nim` | `nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b` | `NVIDIA_API_KEY` |
| 3 | `openrouter` | `openrouter/meta-llama/llama-3.2-3b-instruct:free` | `OPENROUTER_API_KEY` |
| 4 | `gemini` | `gemini/gemini-flash-latest` | `GEMINI_API_KEY` |
| 5 | `meta` | `meta/muse-spark-1.3` | `META_API_KEY` |

Public and invited jobs use the verified free generation subset of Groq, OpenRouter, and Gemini. NVIDIA trial access is for private owner evaluation on the built-in synthetic fixture. Keep trial output private. OpenRouter uses the exact free model with upstream fallback disabled. Mistral API access requires billing, so its generation route is excluded. [NVIDIA trial terms](https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf) · [OpenRouter routing](https://openrouter.ai/docs/guides/routing/provider-selection) · [Mistral usage policy](https://docs.mistral.ai/admin/billing-usage/usage-limits)

Quota exhaustion skips a route. A provider `429` stores a cooldown in PostgreSQL. An availability failure skips that route for the rest of the operation. Authentication, invalid input, rejected output, and application budget exhaustion stop the request. Transcription and embeddings use separate verified routes.

- **Groq transport:** The native LiteLLM adapter can fail when a valid response omits `service_tier`. The app uses Groq's fixed OpenAI-compatible chat endpoint and retains Groq accounting. Retries and redirects are disabled. Groq STT uses its separate SDK. [Groq compatibility](https://console.groq.com/docs/openai)
- **NVIDIA transport:** Use the fixed NVIDIA OpenAI-compatible endpoint with SDK retries disabled. [NVIDIA API reference](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-5-lightning-30b-a3b-infer)
- **LangChain integration:** LangChain chains use the guarded runnable around the in-process LiteLLM Router. Reading the Router response directly preserves refusal metadata for validation.
- **Dependency review:** the local wheels were checked against PyPI hashes and inspected for unexpected Python startup hooks. The backend lock pins the exercised versions. Linux packaging and the 512 MiB container memory gate remain unverified. See [benchmark notes](BENCHMARK_NOTES.md).
- **Quality:** exact quotation validation checks source provenance. It does not establish that a quotation entails every claim. See the [offline actual-embedding comparison](BENCHMARK_NOTES.md#optional-local-embedding-experiment). Formal evaluation and hosted-provider quality remain pending.

## Private owner evaluation

For an authorized local NVIDIA embedding test, verify the exact model and remaining trial allowance under the [NVIDIA trial terms](https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf). Configure `NVIDIA_API_KEY` and an explicit `nvidia-nemotron` embedding entry. To exercise it directly, use that as the only embedding entry for the private run. Configure a verified generation profile separately. After initializing the local database and preparing the reranker, set a private `RATE_LIMIT_SECRET` and enable provider calls in the local environment. Run `python -m backend.cli --owner-evaluation` with `ENABLE_PAID_META=false`. The CLI uses the built-in synthetic transcript, skips STT, and accepts only the numbered synthetic questions. Keep results private. Leave hosted environments in sample mode with provider calls disabled.

The existing hosted owner flow supports separately authorized generation evaluations with an approved embedding route. In that flow, submit `POST /jobs` with only `demo_acknowledged=true` and an `X-Owner-Evaluation` header matching the private `OWNER_EVALUATION_TOKEN`. Send the same header and the returned `Authorization: Bearer <job_token>` on subsequent requests. Chat accepts the synthetic questions returned at creation. Keep owner evaluation jobs private when choosing jobs for MCP sharing.

To enable the paid Meta last resort, set `ENABLE_PAID_META=true` only in the intended owner environment. Configure the Meta route with `verified_free: false` and reviewed decimal-string `input_price_per_million` and `output_price_per_million` in USD. The published uncached rates are $1.25 and $4.25 per million tokens. Verify your account's rates before enabling the route. Explicitly opt in with `--allow-paid` on the owner CLI or `X-Owner-Allow-Paid: true` on the owner creation or chat request. Use the same PostgreSQL usage ledger for local and hosted runs sharing a Meta account. [Meta Muse Spark pricing](https://dev.meta.ai/models/muse-spark)

The ledger reserves an estimated maximum of $0.01 per job and $0.05 per UTC day and allows one paid attempt per job across processing and chat. A paid call can rescue one generation stage. If later stages also exhaust their free routes, the run can still stop. Failed and ambiguous attempts retain their reservations.

## Verification

The offline suite tests fixed provider destinations, one outbound request per attempt, persisted cooldowns, quota reservations, indexing fallback, pinned query embeddings, and atomic deletion. PostgreSQL tests use disposable data and isolated schemas. The reranker test uses the pinned TinyBERT assets. The Chrome mock journey covers explicit submission through **Analyse**, progress, citations, transcript expansion, refresh, and deletion. See the [roadmap status](ROADMAP_STATUS.md#verified-locally) for measured results and the [benchmark notes](BENCHMARK_NOTES.md) for resource and retrieval experiments.
