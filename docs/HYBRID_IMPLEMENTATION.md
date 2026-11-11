# Hybrid retrieval implementation and operator guide

Updated 2026-11-11. The implementation is local on `work/project-updates`.

New jobs store sanitized timestamped chunks and use stable IDs across PostgreSQL, dense pgvector search, and LangChain BM25. Each branch returns up to ten matches. RRF with constant 60 selects up to twelve candidates for the required TinyBERT cross-encoder. The top four passages go to LangChain for generation and quotation validation. Chat adds citations and retrieval metadata to the existing answer response. Legacy collections retain their original vectors and require explicit reprocessing for hybrid chat.

The server rejects missing model profiles or reranker assets before dispatching the corresponding provider work. It reserves STT requests and audio duration separately from generation and embedding attempts. Requests and uncertain attempts remain charged to application budgets after failures and deletion. A conservative forecast checks the sanitized transcript after STT and before generation or indexing. A recording can meet the upload limit and still exceed the processing budget. The job-wide ceilings are 24 text attempts, 60,000 reserved input units and 12,000 reserved output tokens. UTF-8 byte bounds are conservative reservations. Each provider's configured caps can further restrict admission.

## Local setup

Use Python 3.11 and `pip install -r backend/requirements.lock`. Run `python scripts/prepare_reranker.py` to prepare the verified local model. The Dockerfile also prepares it during the image build. The [manifest](../backend/model_assets/manifest.json) records the FlashRank ONNX export, the source revision, license, attribution and hashes. Local model binaries are ignored by Git. Runtime inference uses the prepared files.

Keep `.env` private. `.env.example` starts with providers disabled and empty profiles. A local API also needs a disposable PostgreSQL database with pgvector. The schemas add chunk metadata and accounting tables. They preserve existing job rows and legacy vectors.

| Setting | Required values after operator verification |
|---|---|
| `STT_PROFILES_JSON` | JSON array with one entry per chosen provider. Each object has `provider`, `model`, `keyenv`, `verified_free`, `rpm`, `rpd`, `audio_seconds_hour`, `audio_seconds_day`. Use `groq` with `GROQ_API_KEY` for English or `sarvam` with `SARVAM_API_KEY` for Hinglish. Each limit is a positive integer from the applicable account policy. |
| `LLM_ROUTES_JSON` | JSON array of explicit routes. Each object has unique `alias`, `tier` (`economy` or `strong`), `provider`, provider-prefixed `model`, `api_key_env`, `verified_free`, `input_limit_tokens`, `rpm`, `tpm`, and `rpd`. Use verified account ceilings. The hosted recruiter demo uses economy. |
| Gemini embedding profile | `GEMINI_API_KEY`, `ENABLE_GEMINI_EMBEDDINGS=true`, `GEMINI_EMBEDDINGS_VERIFIED_FREE=true`, and positive `GEMINI_EMBEDDINGS_RPM`, `_TPM`, `_RPD`. New indexes use `gemini-embedding-001` with 768 dimensions. |
| Public admission | `ENABLE_PROVIDER_CALLS=true` requires a stable private `RATE_LIMIT_SECRET` of at least 32 characters. Enable it only after verifying free entitlements and privacy terms for each operation. |

`verified_free` is an operator attestation. Shared Gemini usage obeys the lowest configured ceiling across the generation and embedding profiles. Use synthetic or permitted non-personal material. Hosted STT receives original audio. Text redaction preserves names and can miss sensitive data. Free-tier Gemini content is subject to Google's data-use terms. [Gemini terms](https://ai.google.dev/gemini-api/terms)

## Provider and release gates

Configure the economy routes below after verifying the corresponding account, model, and terms. The gateway sets the order independently of the JSON array order.

| Order | `provider` | `model` | `api_key_env` |
|---|---|---|---|
| 1 | `groq` | `groq/openai/gpt-oss-20b` | `GROQ_API_KEY` |
| 2 | `nvidia_nim` | `nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b` | `NVIDIA_API_KEY` |
| 3 | `openrouter` | `openrouter/meta-llama/llama-3.2-3b-instruct:free` | `OPENROUTER_API_KEY` |
| 4 | `gemini` | `gemini/gemini-flash-latest` | `GEMINI_API_KEY` |
| 5 | `meta` | `meta/muse-spark-1.3` | `META_API_KEY` |

Public and invited jobs use the verified free subset of Groq, OpenRouter, and Gemini. NVIDIA trial access is for private owner evaluation on the built-in synthetic fixture. Keep trial output private. OpenRouter uses the exact free model with upstream fallback disabled. Mistral API access requires billing, so its generation route is excluded. [NVIDIA trial terms](https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf) · [OpenRouter routing](https://openrouter.ai/docs/guides/routing/provider-selection) · [Mistral usage policy](https://docs.mistral.ai/admin/billing-usage/usage-limits)

Quota exhaustion skips a route. A provider `429` stores a cooldown in PostgreSQL. An availability failure skips that route for the rest of the operation. Authentication, invalid input, rejected output, and application budget exhaustion stop the request. Transcription and embeddings use separate verified routes.

- **Groq transport:** The native LiteLLM adapter can fail when a valid response omits `service_tier`. The app uses Groq's fixed OpenAI-compatible chat endpoint and retains Groq accounting. Retries and redirects are disabled. Groq STT uses its separate SDK. [Groq compatibility](https://console.groq.com/docs/openai)
- **NVIDIA transport:** Use the fixed NVIDIA OpenAI-compatible endpoint with SDK retries disabled. [NVIDIA API reference](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-5-lightning-30b-a3b-infer)
- **LangChain integration:** LangChain chains use the guarded runnable around the in-process LiteLLM Router. Reading the Router response directly preserves refusal metadata for validation.
- **Dependency review:** the local wheels were checked against PyPI hashes and inspected for unexpected Python startup hooks. The backend lock pins the exercised versions. Linux packaging and the 512 MiB container memory gate remain unverified. See [benchmark notes](BENCHMARK_NOTES.md).
- **Quality:** exact quotation validation checks source provenance. It does not establish that a quotation entails every claim. See the [offline actual-embedding comparison](BENCHMARK_NOTES.md#optional-local-embedding-experiment). Formal evaluation and hosted-provider quality remain pending.

## Private owner evaluation

For an authorized internal test, configure `NVIDIA_API_KEY` and the verified NVIDIA route. Locally, use `python -m backend.cli --owner-evaluation` for the built-in synthetic transcript and questions. On the hosted API, submit `POST /jobs` with only the form field `demo_acknowledged=true` and the `X-Owner-Evaluation` header matching the separate `OWNER_EVALUATION_TOKEN` secret. Use `secrets.token_urlsafe(32)` to generate the secret. Send the same header and the returned `Authorization: Bearer <job_token>` on subsequent requests. Chat accepts the synthetic questions returned at creation. Keep owner evaluation results private, including when selecting jobs for MCP sharing.

To enable the paid Meta last resort, set `ENABLE_PAID_META=true` only in the intended owner environment. Configure the Meta route with `verified_free: false` and reviewed decimal-string `input_price_per_million` and `output_price_per_million` in USD. The published uncached rates are $1.25 and $4.25 per million tokens. Verify your account's rates before enabling the route. Explicitly opt in with `--allow-paid` on the owner CLI or `X-Owner-Allow-Paid: true` on the owner creation or chat request. Use the same PostgreSQL usage ledger for local and hosted runs sharing a Meta account. [Meta Muse Spark pricing](https://dev.meta.ai/models/muse-spark)

The ledger reserves an estimated maximum of $0.01 per job and $0.05 per UTC day and allows one paid attempt per job across processing and chat. A paid call can rescue one generation stage. If later stages also exhaust their free routes, the run can still stop. Failed and ambiguous attempts retain their reservations.

## Verification

The provider failover update passed all 181 offline backend tests with disposable PostgreSQL and pgvector. Intercepted transport tests verified fixed destinations and one outbound HTTP request per attempt across the configured providers. Database tests covered persisted cooldowns and concurrent paid reservations. The provider accounts still require live entitlement checks before activation.

The offline suite covers real PostgreSQL budget, cleanup and API tests and a pgvector 0.8.1 test with 768- and 1,024-dimensional collections. The vector fixture uses synthetic embeddings in an isolated schema. Tests exercise real TinyBERT inference with the pinned assets. Four frontend tests and the Vite production build passed. A browser smoke test used intercepted API calls to verify acknowledgement before upload, explicit strong-tier selection, and approximate source timestamps. See the [roadmap status](ROADMAP_STATUS.md) for current verification.

- [Backend test log](../output/validation/roadmap-tests.log)
- [Browser citation screenshot](../output/playwright/hybrid-citations.png)
- [Local resource and retrieval fixture benchmarks](BENCHMARK_NOTES.md)
