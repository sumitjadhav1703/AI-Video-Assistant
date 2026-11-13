# Future improvement: v2 RAG pipeline (parked, not active)

**Status: not adopted.** The shipped pipeline is v1, the version measured in
[evaluation/EVALUATION_REPORT.md](../../evaluation/EVALUATION_REPORT.md), plus the embedding fallback
chain. This folder keeps the v2 work so it can be picked up later. None of it runs in the app.

- `v2.patch`: every v2 code change against commit `7c9e3f0`. It touches 29 files (backend, tests,
  evaluation tooling, CI) and applies cleanly to that commit.
- `reports/`: measured results of the first v2 iteration. Summary reports only; raw model outputs
  were kept out of Git.

## What v2 changes, and why (evidence from the v1 evaluation)

| # | Change | Where (in the patch) | v1 evidence it targets |
|---|---|---|---|
| 1 | Quote matching tolerates whitespace, space-before-punctuation and curly or straight apostrophes | `backend/core/rag_engine.py` `_quote_pattern`, `_find_quote` | 4 of 14 rejected outputs differed only by caption spacing (`"dynamic  with"`, `"communities ."`) |
| 2 | Re-credit a quote to the supplied chunk that contains it, or across two adjacent supplied chunks | `rag_engine.py` `_cite`, `_overlap` | 5 of 14 rejected outputs were real text crossing a chunk boundary |
| 3 | A stitched quote ("…") is split, and every part must be a real quote | `rag_engine.py` `validate_grounded_answer` | 3 of 14 were stitched; real stitches are accepted, fabricated parts still rejected |
| 4 | An abstention with an empty `answer` is valid | `rag_engine.py` `GroundedAnswer` | 2 of 14 were correct abstentions rejected by `min_length=1`, which led to the 503s |
| 5 | Numbers and names in an answer must appear in the job's transcript or the question | `rag_engine.py` `_unsupported_terms` | U-005: two models answered "United States", caught only by luck |
| 6 | Interpolated quote timestamps (shown with "~") instead of the 40–70 s chunk range | `rag_engine.py` `_at`, `_citation` | Citations pointed at whole-chunk ranges |
| 7 | New system prompt: transcript wording, one contiguous quote of 4–25 words, premise and ambiguity rules, concise answers | `rag_engine.py` `SYSTEM_PROMPT` | Long boundary-crossing quotes; ambiguity not flagged |
| 8 | Chat output cap 768 (was 1024) | `rag_engine.py` `_answer_question` | Observed maximum was 515 output tokens |
| 9 | Sentence-aware chunking (~500 characters, 1-sentence overlap, never mid-word) | `backend/core/chunks.py` | 20 of 21 v1 chunk boundaries cut mid-word or mid-sentence |
| 10 | Successful attempts settle the per-minute token window to reported usage | `backend/core/provider_budget.py` `record_attempt_result` | Reservations ran 4–7× above use, which hit Gemini's per-minute token cap |
| 11 | Eval tooling: version tags, pinned-route A/B, quote coverage@4, top-5 and rerank-blend variants, paired comparison with a pre-registered gate, offline CI job | `evaluation/...`, `.github/workflows/ci.yml` | Needed for a fair v1-vs-v2 comparison |

Tests cover each change: 10 new backend tests and updated chunk, evidence and budget tests. Before
parking, the backend suite passed (273 tests; DB tests against a throwaway pgvector) and so did the
eval suite (47 tests).

## What was measured (interim, not final)

These are from `reports/comparison_v1-pinned_vs_v2-iter1.md`. Both runs used the same pinned generator
(NVIDIA Nemotron 3.5 Lightning) and the same embedding model (OpenRouter Nemotron embed), over the 31
questions both runs had answered:

| | v1 | v2 (iteration 1) |
|---|---|---|
| HTTP 503 (every model output rejected) | 5 | **0** |
| Faithfulness (DeepEval, paired n=25) | 1.000 | 1.000 |
| Answer Relevancy (paired n=26) | 0.981 | 0.941 (Δ −0.040, CI includes 0; one judge false negative on H-003) |
| Contextual Precision | 0.920 | 0.933 |
| Quote coverage@4 | 1.000 | 0.974 (within the 0.05 tolerance) |
| Citation validity | 100% | 100% |
| End-to-end p95, paired questions both answered | 4.5 s | 6.3 s, **failed the latency gate** |

**Offline replay** (`reports/v1_rejected_outputs_replay.txt`). v1's 14 rejected model outputs were
re-run through the v2 validator with the same evidence:
- 9 accepted;
- 2 valid abstentions;
- 3 still rejected, all correctly: a hallucinated name, an invented acronym expansion, and a
  spliced quote.

None of v1's 43 accepted outputs was rejected.

## Why it is parked

- **The latency gate failed.** v2 answers were about 45% longer (output-token median 106 → 154), and
  the run shared the NVIDIA account with two concurrent runs.
- **The fix is not measured.** A concision rule was added to the prompt but never re-measured.
- **The A/B is incomplete.** The last 14 v1 questions and the v2 repeat judge run were not done
  before the decision to ship v1.

## How to resume

```bash
git apply future-improvements/v2-rag-pipeline/v2.patch   # on top of 7c9e3f0; resolve embedding_routes.py if the fallback fix is present
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s tests
EVAL_RUN_TAG=v2 EVAL_PIN_CHAT_ROUTE=nvidia-nemotron evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage index
EVAL_RUN_TAG=v2 EVAL_PIN_CHAT_ROUTE=nvidia-nemotron evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage answer --scope owner
EVAL_RUN_TAG=v2 EVAL_ALLOW_PAID_JUDGE=1 EVAL_JUDGE_BUDGET_USD=2.7 evaluation/.venv/bin/python -m evaluation.runners.run_eval --mode local --stage judge --judge-stages generation --no-sanity
evaluation/.venv/bin/python -m evaluation.runners.compare v1-pinned v2
```

Run v1 and v2 on the same generator and embedding model, one at a time (not concurrently), so
latency is comparable. Adopt v2 only if the comparison gate says it is better.

**Judge spend for this work:** $3.58 (v2 iteration 1: $2.02, v1-pinned: $1.56), within the $8 cap.
