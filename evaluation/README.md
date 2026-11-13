# RAG evaluation framework

Reproducible evaluation of the **existing** AI Video Assistant chat pipeline. Nothing here changes
production code, routing or defaults: the adapter calls the app's own functions and observes them.

- Pipeline under test: `ask_question(load_rag_chain(job))`. That is pgvector dense k=10, BM25 k=10,
  RRF (60) capped at 12, then the local TinyBERT reranker to the top 4. Generation is a strict JSON
  grounded answer; each quote must be an exact match of at least 4 words, and timestamps come from
  the server.
- Dataset: 45 goldens over a public-domain NASA talk ([source](dataset/source/SOURCE.md)).
- Scores: DeepEval 4.3.4 metrics, application-specific deterministic checks, IR metrics against
  gold chunk ids, and latency. Each is reported separately.

## Modes

| Mode | What runs | Network |
|---|---|---|
| `offline` | Dataset validation, BM25 and BM25+rerank IR, the adversarial structure suite, reports | Loopback only; any other socket raises `NetworkBlocked`. `ENABLE_PROVIDER_CALLS=false`. |
| `local` | Indexing and answering through the real app (free routes), the Meta judge (paid, capped), reports | Allowlist: Gemini, Groq, OpenRouter, NVIDIA, and `api.meta.ai` during judge stages only. Confident AI and PostHog are refused. |

`local` means **local execution with remote inference**. It is never described as offline.
No local judge model exists on this machine, so offline mode reports DeepEval metrics as
*not run* and never estimates them.

The network guard patches Python sockets. It does not see C-level clients such as libpq or grpc. The
database is guarded separately: it must be on loopback, be named `ava_eval`, and not use port 55432.
DeepEval telemetry is opted out (`DEEPEVAL_TELEMETRY_OPT_OUT=YES`) and its `.env` autoload is off.

## Safety rails (enforced in code, tested)

- `ENABLE_PAID_META`, `ENABLE_PUBLIC_PAID_FALLBACK` and `ENABLE_NVIDIA_PUBLIC` are forced to `false`
  for the app under test, whatever `.env` says. The app can never route to Meta.
- `DATABASE_URL` from `.env` is dropped. Only `EVAL_DATABASE_URL` is used, and only if it is a
  loopback database named `ava_eval`, not on port 55432 (your `ai-video-pgvector`).
- The judge runs only with `EVAL_ALLOW_PAID_JUDGE=1` and a positive `EVAL_JUDGE_BUDGET_USD`.
  - Before each call, it refuses if `spent + worst_case(next call)` would exceed the cap.
  - After each call, it books the real cost from `usage`, counting reasoning tokens at the output
    rate, in `reports/judge_ledger.json`.
  - A `--pilot` run is capped at $0.50.
- `META_API_KEY` is read from the environment only. It is never printed, logged or written. Error
  messages carry only the exception class and HTTP status.
- The judge uses the standard `muse-spark-1.3` model; the `-contributor` (training) tier is refused.
- There is no Confident AI login and no upload. `CacheConfig(write_cache=False)`.

## Meta judge findings (13 Nov 2026)

- **What the existing integration calls.**
  - Speech-to-text: `POST https://api.meta.ai/v1/asr/transcribe` (`muse-voice-transcribe-1.0`).
  - The paid chat route: `https://api.meta.ai/v1/chat/completions` (`muse-spark-1.3`).
- **Text generation.** The chat model is OpenAI-compatible, which suits DeepEval's custom-model interface.
- **Cost.** $1.25 per million input tokens and $4.25 per million output tokens; reasoning bills as
  output. These are secondary-source prices, so re-check them before the run.
- **Data use.** The Meta Model API terms of 9 Oct 2026 allow this use:
  - §5.1: the standard tier is not used for training.
  - §10.1(ix): evaluating your own systems is allowed.
  - §10.1(xi): do not publish benchmarks of Meta's service. These reports evaluate this app, not Meta.
- **Data sent.** Only public-domain NASA text and the app's answers about it go to Meta.
- **Not yet verified.** Whether the judge honours `response_format: json_schema` is confirmed by
  `--stage probe`. If it returns a 400, the judge switches to prompt-confined JSON with pydantic
  validation and one retry.

## Dataset

`dataset/goldens.jsonl` is hand-authored, and `dataset/goldens_resolved.jsonl` is derived from it
by `validate.py`.

| Category | n | Expected behaviour |
|---|---|---|
| direct_factual | 10 | answer |
| multi_passage | 6 | answer (evidence in 2+ chunks) |
| numerical_date | 6 | answer |
| named_entity | 5 | answer |
| multi_hop | 5 | answer (facts must be combined) |
| unanswerable | 6 | abstain (2 are near-misses) |
| ambiguous | 3 | grounded answer to either reading, or abstain |
| misleading | 4 | correct the false premise, or abstain |

**Each record holds:**
- the question, expected answer, relevant facts and exact evidence quotes, and the expected behaviour
- for unanswerable items, `absent_terms` (words an answer would need, which must not occur in the transcript)
- for misleading items, `premise_correction_terms`

**`validate.py` derives** `gold_chunk_ids`, cue-level `start_ms`/`end_ms` per quote, `source_id` and `job_id`.

**`validate.py` fails the build** if any of these happen:
- a quote is not an exact, unique substring of the transcript
- a quote is shorter than 4 words or 20 characters
- a quote crosses a chunk boundary
- an absent term occurs in the transcript
- the category counts drift

Ground truth was authored by Claude Opus 5.5, not by a question generator, and verified mechanically.
`human_review` stays `pending` until you review it.

Chunks come from the app's own `prepare_documents` (500 characters, step 450): 22 chunks, job id
`9e08293bb466d20b97edb862ec6eba2f`.

## Metrics

### DeepEval (LLM-as-a-judge; answerable categories only, n = 32)

| Metric | Threshold | Stage(s) | Why this threshold |
|---|---|---|---|
| Faithfulness | 0.8 | generation | The app forces quoted evidence; unsupported claims should be rare |
| Answer Relevancy | 0.7 | generation | Same as the reference suite |
| Contextual Precision | 0.7 | generation (= post-rerank top 4), pre-rerank (RRF top 12) | Same as the reference suite |
| Contextual Recall | 0.7 | same | Same as the reference suite |
| Contextual Relevancy | 0.5 | same | Scored per statement; 500-character chunks carry off-topic sentences by design |

- Average score is the primary signal and pass rate is secondary: pass rate jumps when scores cluster
  near the threshold.
- Abstention-style cases are not judged; AnswerRelevancy and Recall are undefined for a correct abstention.
- Four judge sanity controls (fabricated, off-topic, irrelevant context, contradiction) must score
  low. If they don't, distrust the judge.

### Application checks (deterministic, free)

- **Citations.**
  - The chunk is in the retrieved context.
  - The quote is an exact substring of that chunk.
  - The timestamps equal the chunk's.
  - Cited chunks overlap the gold chunks.
- **Behaviour.** Per-category accuracy of answer versus abstain, plus abstention precision, recall
  and F1 and the false-abstention rate.
- **Structure.**
  - Exact result and citation keys.
  - 15 adversarial raw model outputs fed to `validate_grounded_answer`: prose, code fence, extra
    fields, a short quote, a fabricated quote, an unknown chunk, a wrong chunk, a string boolean,
    truncated JSON, and an empty context.

### Retrieval (gold chunk ids, k=4)

- Measures: hit, recall, precision, MRR and nDCG.
- Variants:
  - `dense_only`, `bm25_only` and `hybrid_rrf` (rerank off): taken from the same captured request.
  - `hybrid_rerank`: production.
  - Offline only: `bm25_rerank`.
- A variant counts as better or worse only if the difference exceeds 0.05 **and** the paired
  bootstrap 95% CI excludes 0.

### Latency (reported apart from quality)

- **Measured:** app telemetry `dense_retrieval`, `sparse_retrieval`, `rrf` and `rerank`, plus
  generation time per provider attempt and end-to-end time per question.
- **Counted:** candidate counts, provider attempts, retries, failures, and the models used.
- **Cold runs:** the first question of a run is flagged `cold` and excluded from the warm stats.
- **Query embeddings:** all questions are embedded in one batched request (route caps: Gemini allows
  20 requests per day), and the request is timed separately. So `dense_retrieval` covers the
  pgvector search only.

### Evaluation-only deviation (documented)

The app's lifetime job budget (24 attempts, 60k input tokens, 12k output tokens) is applied **per
question**, not across all 45 questions on the single evaluation job. Each question is treated like
its own session. Provider rate caps (rpm, tpm, rpd) are untouched.

## Setup (already done)

```bash
python3.11 -m venv evaluation/.venv
evaluation/.venv/bin/python -m pip install -r backend/requirements.lock
evaluation/.venv/bin/python -m pip install --no-deps deepeval==4.3.4   # then its deps, see below
```

deepeval 4.3.4 declares `click<8.4`, but the locked `huggingface-hub` needs `click>=8.4.2`. So
deepeval was installed with `--no-deps`, followed by its declared dependencies. The production lock
is unchanged, and `click` stays at 8.5.0; deepeval uses it only for its CLI.

## Run tomorrow (each step separately approved)

Run from the repository root in one shell.

**Step 0.** Start a disposable database. A named volume keeps the index and per-day rate counters across restarts.

```bash
export PATH=/usr/local/bin:$PATH
docker run -d --name ava-eval-pg -e POSTGRES_PASSWORD=ava-eval-local -e POSTGRES_DB=ava_eval -p 127.0.0.1:55491:5432 -v ava-eval-pg:/var/lib/postgresql/data pgvector/pgvector:pg16
```

```bash
docker exec ava-eval-pg psql -U postgres -d ava_eval -c 'CREATE EXTENSION IF NOT EXISTS vector'
```

```bash
export EVAL_DATABASE_URL=postgresql://postgres:ava-eval-local@127.0.0.1:55491/ava_eval
```

**Step 1.** Index. This makes about 1–2 free Gemini embedding requests.

```bash
evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage index
```

**Step 2.** Answer all 45 questions: 1 batched query-embedding request plus about 45 free
generation calls. The run is resumable. If it stops on a daily cap, rerun the same command later.

`--scope public` mirrors the live demo, whose chat route is Gemini Flash only (about 17 answers
per day). `--scope owner` adds the free owner-only NVIDIA route, never a paid one.

```bash
evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage answer --scope owner
```

**Step 3.** Free interim report: deterministic checks, IR experiments and latency.

```bash
evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage report
```

**Step 4.** Paid: one probe call, well under $0.01.

```bash
EVAL_ALLOW_PAID_JUDGE=1 EVAL_JUDGE_BUDGET_USD=0.05 evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage probe
```

**Step 5.** Paid pilot on 3 cases, capped at $0.50. It prints the measured cost per case and a
full-run projection.

```bash
EVAL_ALLOW_PAID_JUDGE=1 EVAL_JUDGE_BUDGET_USD=0.50 evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage judge --pilot 3
```

**Step 6.** Paid full judge run plus sanity controls. Set the cap you approve. The unmeasured
estimate before the pilot is about $3–7.

```bash
EVAL_ALLOW_PAID_JUDGE=1 EVAL_JUDGE_BUDGET_USD=10 evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage judge
```

**Step 7.** Final reports.

```bash
evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage report
```

**Cleanup** (destroys the eval database only):

```bash
docker rm -f ava-eval-pg && docker volume rm ava-eval-pg
```

## Offline mode and tests

```bash
evaluation/.venv/bin/python -m evaluation.dataset.validate --check
```

```bash
evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode offline
```

```bash
PYTHON_DOTENV_DISABLED=1 evaluation/.venv/bin/python -m unittest discover -s evaluation/tests -t . -v
```

The DB integration test is opt-in. Point it at a **throwaway** `ava_eval` database, never the run database:

```bash
EVAL_TEST_DATABASE_URL=postgresql://postgres:evaltest@127.0.0.1:55492/ava_eval PYTHON_DOTENV_DISABLED=1 evaluation/.venv/bin/python -m unittest evaluation.tests.test_db_integration -v
```

## Reports (`evaluation/reports/`)

`evaluation_summary.md`, `metrics.json`, `metrics.csv`, `test_case_results.json`,
`retrieval_analysis.json`, `latency_results.json`, `failure_analysis.md` and
`experiment_comparison.md`. A stage that did not run is labelled *not run*, never filled in.

`raw/` holds per-case captures. It is gitignored because it contains the free models' raw outputs.

## Limitations

- One 13.5-minute source with 22 chunks, so absolute retrieval scores are optimistic. With 4 of 22
  chunks returned, chance-level recall is already about 0.18.
- A single LLM judge and a single run, so judge variance is unmeasured. Registry tolerances are
  provisional until two identical runs give a noise floor.
- Free generation routes change with availability; the model used is recorded per case.
- Audio transcription is not evaluated. The captions stand in for the transcriber's output.
