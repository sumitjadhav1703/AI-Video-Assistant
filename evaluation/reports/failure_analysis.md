# Failure analysis

Answer stage not run: no app answers were captured, so no request, behaviour or citation failures can be reported.

## Request errors

Not run.

## Answer/abstain behaviour failures

Not run.

## Invalid citations

Not run.

## DeepEval metric failures

Judge not run.

## Adversarial structure cases

- valid_json: expected answer, got answer -> pass
- valid_json_in_code_fence: expected answer, got answer -> pass
- quote_in_different_case: expected answer, got answer -> pass
- prose_only: expected abstain, got abstain -> pass
- extra_top_level_field: expected abstain, got abstain -> pass
- extra_evidence_field: expected abstain, got abstain -> pass
- quote_too_short: expected abstain, got abstain -> pass
- fabricated_quote: expected abstain, got abstain -> pass
- unknown_chunk_id: expected abstain, got abstain -> pass
- quote_from_wrong_chunk: expected abstain, got abstain -> pass
- abstained_true: expected abstain, got abstain -> pass
- empty_evidence: expected abstain, got abstain -> pass
- string_boolean: expected abstain, got abstain -> pass
- truncated_json: expected abstain, got abstain -> pass
- empty_retrieval_context: expected abstain, got abstain -> pass
