# Evaluation run log — 13 November 2026

Branch `eval/deepeval-framework`. Mode `local` (local execution, remote inference). Generation scope:
`owner`, which means free routes only, with `allow_paid=False`. Judge: Meta `muse-spark-1.3`, paid
and capped. Every number below was copied from command output, `reports/raw/run_log.jsonl`, the
eval DB, or `reports/judge_ledger.json`.

## Step 0 — disposable database (12:15 UTC)

```bash
docker run -d --name ava-eval-pg -e POSTGRES_PASSWORD=ava-eval-local -e POSTGRES_DB=ava_eval -p 127.0.0.1:55491:5432 -v ava-eval-pg:/var/lib/postgresql/data pgvector/pgvector:pg16
docker exec ava-eval-pg psql -U postgres -d ava_eval -c 'CREATE EXTENSION IF NOT EXISTS vector'
export EVAL_DATABASE_URL=postgresql://postgres:ava-eval-local@127.0.0.1:55491/ava_eval
```

Outcome: the container started and the `vector` extension was created. The developer DB
(`ai-video-pgvector`, port 55432) was not touched.

## Step 1 — index (12:15:48 UTC)

```bash
evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage index
```

Outcome:
- 22 chunks indexed through the app's own `build_vector_store`.
- Route `gemini-embeddings`, model `gemini-embedding-001`, 768 dimensions.
- 2,195 ms in total.
- One embedding request: provider attempt #1, 10,957 input tokens.

## Step 2 — answer (12:15:55 UTC onward)

```bash
evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage answer --scope owner
```

**First attempt.** All 45 questions were embedded in one batched request (attempt #2, 3,043 tokens,
2,303 ms). After that, 4 answers succeeded. On NASA-F-005 the run stopped with `RuntimeError: No
eligible generation route`.

**Diagnosis**, from the `provider_attempts` table in the eval DB:
- **Gemini per-minute limit.** Gemini's per-minute ceiling is the minimum across the app's Gemini
  routes, and the embedding route's 30,000 tokens per minute is the lowest. Each chat attempt
  reserves about 3.4k input plus 1,024 output tokens, so after the two embedding requests and three
  chat answers that minute's Gemini allowance was used up.
- **Groq per-minute limit.** Groq's 8,000 tokens per minute allows one answer per minute.
- **The other routes failed:**
  - On F-004, `nvidia-nemotron` returned a quote spanning a chunk boundary. Chunk 3 begins mid-word
    ("hat carbon dioxide…"), so the quote "that carbon dioxide accumulates…" was not found in it.
  - The app's strict grounding validator rejected that answer and failed over to Groq, as designed.
  - On F-005, NVIDIA and OpenRouter were tried; with Gemini and Groq still capped for that minute,
    no eligible route was left.

These are **per-minute** caps, not daily ones. The runner treated them as a stop condition.

**Fix**, in `evaluation/runners/adapter.py` only, with a unit test added: when no route is eligible,
the runner waits 65 s and retries the same question, up to 3 times, and only then stops. The caps
are respected, not bypassed. The calls from failed attempts are now kept for diagnosis.

**Second attempt.** 32 more answers. Five questions waited for per-minute caps (E-003, M-004,
M-005, H-005, U-005). U-005 stayed blocked after 3 waits and the run stopped. By then Gemini had
used its **daily** cap of 20 requests: 2 embedding requests plus 18 chat attempts.

**Second diagnosis (a genuine app finding).** On U-005 ("Which country had the most fires detected
by FIRMS in 2021?") every remaining route did reply:
- **NVIDIA and OpenRouter** (both Nemotron) **hallucinated "United States"**. Each cited a real
  FIRMS sentence that does not support the claim. The app rejected both outputs only because the
  quote crossed a chunk boundary. Its grounding check verifies quote location, not semantic support.
- **Groq abstained correctly** with `{"answer": "", "abstained": true, "evidence": []}`. The app's
  `GroundedAnswer` schema requires `answer` to be at least 1 character, so a correct abstention with
  an empty answer counts as malformed output.
- The gateway then failed over and ran out of routes, so a user would have received **HTTP 503
  instead of "not found"**.

**Second fix**, in `evaluation/` only, with a unit test added. The runner now separates two cases:
- **No provider replied** (caps): wait, then stop and resume later.
- **Providers replied but the app rejected every output:** a real failure. It is recorded as
  `error.kind = all_route_outputs_rejected` and scored as an incorrect behaviour; it is not dropped.

The report now counts such errors as incorrect behaviour. Retrieval metrics exclude them because
retrieval was not captured: `ask_question` raised. Production code is unchanged.

**Third attempt** (the last 9 questions; Gemini had no daily quota left, so NVIDIA, Groq and
OpenRouter answered):
- U-005 abstained correctly this time, which shows the free models vary between runs.
- A-002 ("What does the tool do?") and P-003 ("Why does carbon dioxide accumulate most during the
  summer months?") ended as `all_route_outputs_rejected` after 3 waits.
- Final state: **45/45 captured: 43 app results and 2 app errors.**

| Metric | Value |
|---|---|
| Provider attempts | 57 |
| Outputs the app rejected (schema or grounding) and failed over | 14 |
| Questions needing more than 1 attempt | 7 |
| Final answering model: NVIDIA Nemotron 3.5 Lightning 30B-A3B | 16 |
| Final answering model: Gemini 2.5 Flash | 15 |
| Final answering model: OpenRouter Nemotron 3.5 Lightning (free) | 7 |
| Final answering model: Groq gpt-oss-20b | 5 |

## Step 3 — interim report (free)

```bash
evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage report
```

Two report bugs surfaced and were fixed in `evaluation/runners/report.py` and `experiments.py`:
- The failure-analysis writer crashed on cases that have no answer.
- IR metrics counted the 2 errored cases (no captured retrieval) as misses. They are now excluded,
  and n for IR is 37.

The per-model counter also mixed rejected outputs with final answers. Both are now reported
separately.

## Step 4 — judge probe (paid, cap $0.05)

```bash
EVAL_ALLOW_PAID_JUDGE=1 EVAL_JUDGE_BUDGET_USD=0.05 evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage probe
```

- `meta/muse-spark-1.3` accepted `response_format: json_schema` and returned valid JSON.
- One call: 19 input and 267 output tokens, **$0.001159**. Most output tokens are reasoning, even at `reasoning_effort=low`.

## Step 5 — judge pilot (paid, cap $0.50)

```bash
EVAL_ALLOW_PAID_JUDGE=1 EVAL_JUDGE_BUDGET_USD=0.50 evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage judge --pilot 3
```

- Covered 3 cases (E-001, E-002, E-003) × (5 generation metrics + 3 pre-rerank metrics).
- 99 judge calls: 53,628 input and 79,669 output tokens, **$0.4056**, in 52 s for the pre-rerank stage.
- Projection: $0.135 per case × 32 eligible cases = **$4.33**, under the $10 cap, so the run continued.
- No metric errors. Every score came with a judge reason.
- Example finding: on E-001, pre-rerank Contextual Precision is 1.0 but post-rerank (the final
  top 4) is 0.5. The reranker placed an off-topic FIRMS chunk above the speaker-introduction chunk.

## Step 6 — full judge run (paid; $10 approved in total)

```bash
EVAL_ALLOW_PAID_JUDGE=1 EVAL_JUDGE_BUDGET_USD=10 evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage judge
```

**First attempt: only 15 of 32 generation cases and 14 of 32 pre-rerank cases came back.** It
cost $2.0329 for 497 calls. The 4 sanity controls also ran.

**Root cause.** DeepEval 4.3.4 wraps the `asyncio.gather` of *all* test cases in one timeout:
the per-task budget of 180 s plus a buffer (`deepeval/evaluate/execute/e2e.py:619`). With
`max_concurrent=2` and about 25 s of judge work per case, it cancelled the remaining cases.
Because `ignore_errors=True`, it then returned the shorter list **without raising**.

**Fix**, in `evaluation/` only, with a regression test added:
- `DEEPEVAL_DISABLE_TIMEOUTS=1` is now forced. The judge's own client still times out each call at 120 s.
- `judge_runner.judge_stage` compares the returned names with the cases it built. Any shortfall
  becomes an explicit error row (`missing: true`) instead of disappearing.
- The judge stage now resumes: it re-judges only rows that are missing or contain a metric error,
  and keeps complete rows.

**Resume 1** (cap $7.50, so the total cannot exceed $10). Judged the 17 missing generation cases
and 18 missing pre-rerank cases, at **$2.6871** for 584 calls.

That left 10 metric errors:
- 8 were cancellation timeouts inside rows the first attempt had kept.
- 2 were invalid JSON from the judge after one retry: H-002 and M-006, pre-rerank Contextual Precision.

**Resume 2** (cap $1.50). Re-judged the 6 rows with errors, at **$0.4819** for 103 calls.

One error remains: M-006 pre-rerank Contextual Precision. The judge returned invalid JSON twice,
so it is recorded as an error and **not scored**.

**Judge spend, from `reports/judge_ledger.json`:**

| Run | USD | Calls |
|---|---|---|
| probe | 0.0012 | 1 |
| pilot | 0.4056 | 99 |
| full, first attempt | 2.0329 | 497 |
| resume 1 | 2.6871 | 584 |
| resume 2 | 0.4819 | 103 |
| **total** | **5.6087** | **1,284** |

Output tokens exceed input tokens (1,109,192 vs 715,702 across all five runs) because reasoning bills as output; the ledger does not split reasoning from answer tokens.

## Step 7 — final reports

```bash
evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage report
```

All 8 report files were written to `evaluation/reports/`. The headline results follow, copied
from `metrics.json`.

### DeepEval (judge: meta/muse-spark-1.3; 32 answerable cases)

| Stage | Metric | Avg | Passed / judged | Threshold |
|---|---|---|---|---|
| generation (final top 4) | Faithfulness | 1.000 | 32/32 | 0.8 |
| generation | Answer Relevancy | 0.986 | 32/32 | 0.7 |
| generation | Contextual Precision | 0.924 | 28/32 | 0.7 |
| generation | Contextual Recall | 0.938 | 30/32 | 0.7 |
| generation | Contextual Relevancy | 0.237 | 4/32 | 0.5 |
| pre-rerank (RRF top 12) | Contextual Precision | 0.877 | 25/31 (1 error) | 0.7 |
| pre-rerank | Contextual Recall | 1.000 | 32/32 | 0.7 |
| pre-rerank | Contextual Relevancy | 0.126 | 0/32 | 0.5 |

**Judge sanity controls:** all 4 deliberate failures scored **0.0**: a fabricated answer, an
off-topic answer, irrelevant context, and a contradiction. The judge discriminates.

### Application checks (deterministic)

- **Behaviour accuracy:** 43/45 (0.956). Every category is at 100% except:
  - ambiguous: 2/3
  - misleading: 3/4
- **Both failures are app errors (HTTP 503), not wrong answers.** In each, every route's output was
  rejected (see Step 2).
- **Abstention:** precision, recall and F1 are all 1.0. That is 6 of 6 unanswerable questions
  abstained, with 0 false abstentions on 32 answerable questions.
- **False premises:** P-001 and P-004 corrected the premise, citing the transcript. P-002 abstained.
- **Citations:**
  - 56 citations; 100% are in the retrieved context, quote the chunk exactly and carry matching timestamps.
  - 100% of answered cases cite at least one gold chunk.
  - Structure is valid on 43/43 results.
- **Adversarial raw outputs:** 15/15 handled as intended.

### Retrieval: same requests, gold chunk ids, k=4, n=37

| Variant | recall@4 | MRR | nDCG@4 |
|---|---|---|---|
| dense only | 1.000 | 0.946 | 0.951 |
| BM25 only | 0.892 | 0.867 | 0.826 |
| hybrid RRF (rerank off) | 0.964 | 0.928 | 0.909 |
| **hybrid + TinyBERT rerank (production)** | 0.977 | 0.892 | 0.897 |

Each variant compared with production on recall@4 (paired bootstrap, 5,000 resamples):
- **BM25 only:** worse by −0.086, 95% CI [−0.144, −0.032].
- **Dense only:** +0.023, CI [0.000, +0.059]. Not distinguishable.
- **RRF without rerank:** −0.014, CI [−0.041, 0.000]. Not distinguishable.

Offline, with BM25 only, the reranker improves recall@4 from 0.897 to 0.974 (+0.077, CI [+0.026, +0.141]).

The judge's pre- versus post-rerank comparison shows **two cases where the reranker removed needed
evidence:**
- **H-005:** Contextual Recall 1.0 in the top 12, but 0.0 in the final top 4.
- **M-005:** the same drop, from 1.0 to 0.0.

In E-001, E-003 and N-006, an irrelevant chunk was ranked first (generation precision 0.33–0.5).

### Latency (warm, n = 42 retrievals and 52 generation attempts)

| Stage | p50 | p95 |
|---|---|---|
| dense (pgvector search only; query embedding batched separately, 2.3 s for 45 queries) | 5 ms | 6 ms |
| BM25 | 1 ms | 1 ms |
| RRF | 0 ms | 0 ms |
| TinyBERT rerank (≤12 candidates) | 8 ms | 10 ms |
| generation (per provider attempt) | 2,017 ms | 3,694 ms |
| end to end per question | 2,085 ms | 5,128 ms |

Generation is over 99% of latency.
- 57 provider attempts for 45 questions.
- 14 outputs were rejected by the app's validator, which then failed over.
- 7 questions needed more than one attempt.

## Findings worth acting on (production code was not changed)

1. **A correct abstention is rejected when `answer` is empty.**
   - `GroundedAnswer.answer` has `min_length=1` (`backend/core/rag_engine.py:30`).
   - Groq returned `{"answer":"","abstained":true,"evidence":[]}`. The gateway counted that as
     malformed output and failed over.
   - Allowing an empty answer when `abstained` is true would turn some of these 503s into
     correct abstentions.
2. **Quote checks are locational, not semantic.** On U-005, Nemotron's hallucination ("United
   States") was stopped only because its quote crossed a chunk boundary.
3. **Chunk boundaries cut words** (chunk 3 begins "hat carbon dioxide…"). Models that quote the
   full sentence are then rejected. Snapping the 450-character step to whitespace would cut these
   failovers.
4. **The reranker sometimes demotes the evidence that is needed** (H-005, M-005). On this
   single-source corpus dense retrieval alone matched production; that does not justify dropping
   the reranker without a larger dataset.
5. **Contextual Relevancy is low by construction:** one relevant sentence in a 500-character chunk.
   Treat it as a context-size diagnostic, not a pass/fail gate.

## Limitations

- **Small corpus.** One 13.5-minute source with 22 chunks, so absolute retrieval scores are
  optimistic: returning 4 of 22 chunks gives chance-level recall of about 0.18.
- **Mixed generators.** Generation used four free models, because Gemini's daily cap of 20 was
  reached. Per-case models are in `test_case_results.json`.
- **One judge run.** Judge variance is unmeasured, and the registry tolerances are provisional.
- **Model output varies.** U-005 failed once and passed on retry, so a single run is one sample.
- **Unreviewed goldens.** Claude Opus 5.5 authored them and they pass exact-substring checks,
  but no human has reviewed them yet.
