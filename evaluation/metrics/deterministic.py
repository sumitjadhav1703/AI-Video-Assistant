"""Application-specific checks that DeepEval does not cover: citations, abstention and answer structure.

Every function is pure: it takes a captured app result plus the golden record and returns data.
These scores are reported separately from DeepEval's LLM-judged scores.
"""
import json

from backend.core.rag_engine import ABSTENTION, validate_grounded_answer

RESULT_KEYS = {'answer', 'abstained', 'citations', 'retrieval', 'model'}
CITATION_KEYS = {'chunk_id', 'text', 'start_ms', 'end_ms', 'timing_precision'}


def check_structure(result):
    """Exact top-level and citation schema of ask_question's return value."""
    errors = []
    if not isinstance(result, dict):
        return ['result is not an object']
    if set(result) != RESULT_KEYS:
        errors.append(f'unexpected result keys: {sorted(set(result) ^ RESULT_KEYS)}')
    if not isinstance(result.get('answer'), str) or not result.get('answer', '').strip():
        errors.append('answer must be a non-empty string')
    if not isinstance(result.get('abstained'), bool):
        errors.append('abstained must be a boolean')
    citations = result.get('citations')
    if not isinstance(citations, list):
        errors.append('citations must be a list')
        citations = []
    for i, citation in enumerate(citations):
        if not isinstance(citation, dict) or set(citation) != CITATION_KEYS:
            errors.append(f'citation {i} has keys {sorted(citation) if isinstance(citation, dict) else type(citation).__name__}')
    if result.get('abstained') is True and (citations or result.get('answer') != ABSTENTION):
        errors.append('an abstention must use the fixed text and carry no citations')
    if result.get('abstained') is False and not citations:
        errors.append('a non-abstained answer must carry at least one citation')
    return errors


def check_citations(result, final_chunks, quote_spans=None):
    """Each citation must point at a chunk the answer was given, quote it exactly and carry its timestamps.

    final_chunks: {chunk_id: {'text', 'start_ms', 'end_ms'}} for the passages sent to the model.
    quote_spans: optional (start_ms, end_ms) of the caption cues behind each citation, for coverage checks.
    """
    checks = []
    for citation in result.get('citations') or []:
        chunk = final_chunks.get(citation.get('chunk_id'))
        row = {'chunk_id': citation.get('chunk_id'),
               'in_retrieved_context': chunk is not None,
               'exact_quote': bool(chunk) and isinstance(citation.get('text'), str) and citation['text'] in chunk['text'],
               'timestamps_match_chunk': bool(chunk) and citation.get('start_ms') == chunk['start_ms']
               and citation.get('end_ms') == chunk['end_ms']}
        row['valid'] = row['in_retrieved_context'] and row['exact_quote'] and row['timestamps_match_chunk']
        checks.append(row)
    return {'n': len(checks), 'valid': sum(c['valid'] for c in checks), 'all_valid': all(c['valid'] for c in checks),
            'details': checks}


def evidence_alignment(result, golden):
    """Do the cited chunks overlap the human-labelled gold chunks?"""
    cited = {c.get('chunk_id') for c in result.get('citations') or []}
    gold = set(golden.get('gold_chunk_ids') or [])
    if not cited or not gold:
        return {'cited': sorted(cited), 'gold_hit': None, 'citation_precision': None, 'gold_coverage': None}
    return {'cited': sorted(cited), 'gold_hit': bool(cited & gold),
            'citation_precision': len(cited & gold) / len(cited),
            'gold_coverage': len(cited & gold) / len(gold)}


def check_behavior(result, golden):
    """Did the app answer or abstain as the golden expects?"""
    expected = golden['expected_behavior']
    abstained = result.get('abstained') is True
    answer = (result.get('answer') or '').lower()
    gold_hit = evidence_alignment(result, golden)['gold_hit']
    if expected == 'answer':
        correct, reason = (not abstained), ('false abstention' if abstained else 'answered')
    elif expected == 'abstain':
        leaked = [t for t in golden.get('absent_terms', []) if t.lower() in answer]
        correct = abstained
        reason = 'abstained' if abstained else f'answered an unanswerable question{" (mentions " + ", ".join(leaked) + ")" if leaked else ""}'
    elif expected == 'answer_or_abstain':
        correct = abstained or bool(gold_hit)
        reason = 'abstained' if abstained else ('answered with gold evidence' if gold_hit else 'answered without gold evidence')
    elif expected == 'correct_premise_or_abstain':
        corrected = any(t.lower() in answer for t in golden.get('premise_correction_terms', []))
        correct = abstained or corrected
        reason = 'abstained' if abstained else ('corrected the premise' if corrected else 'accepted a false premise')
    else:
        raise ValueError(f'unknown expected_behavior {expected!r}')
    return {'expected': expected, 'outcome': 'abstained' if abstained else 'answered', 'correct': correct, 'reason': reason}


def abstention_metrics(rows):
    """rows: [{'expected': ..., 'outcome': ...}] -> abstention precision/recall/F1 on unanswerable items.

    Positive class = "the app should abstain" (expected_behavior == 'abstain').
    """
    tp = sum(r['expected'] == 'abstain' and r['outcome'] == 'abstained' for r in rows)
    fp = sum(r['expected'] == 'answer' and r['outcome'] == 'abstained' for r in rows)
    fn = sum(r['expected'] == 'abstain' and r['outcome'] == 'answered' for r in rows)
    answerable = sum(r['expected'] == 'answer' for r in rows)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if precision == 0 or recall == 0 else None)
    return {'true_abstentions': tp, 'false_abstentions': fp, 'missed_abstentions': fn,
            'abstention_precision': precision, 'abstention_recall': recall, 'abstention_f1': f1,
            'false_abstention_rate': fp / answerable if answerable else None}


def adversarial_structure_suite(documents):
    """Feed malformed or hostile model outputs straight to the app's validator (no network).

    Returns [{'name', 'expected', 'outcome', 'passed'}]. 'expected' is 'abstain' or 'answer'.
    """
    doc = documents[0]
    chunk_id = doc.metadata['chunk_id']
    good_quote = ' '.join(doc.page_content.split()[3:12])
    other = documents[1].metadata['chunk_id'] if len(documents) > 1 else chunk_id
    valid = {'answer': 'A grounded answer.', 'abstained': False, 'evidence': [{'chunk_id': chunk_id, 'quote': good_quote}]}
    cases = [
        ('valid_json', json.dumps(valid), 'answer'),
        ('valid_json_in_code_fence', '```json\n' + json.dumps(valid) + '\n```', 'answer'),
        ('quote_in_different_case', json.dumps({**valid, 'evidence': [{'chunk_id': chunk_id, 'quote': good_quote.upper()}]}), 'answer'),
        ('prose_only', 'The answer is twenty-three satellites.', 'abstain'),
        ('extra_top_level_field', json.dumps({**valid, 'confidence': 0.9}), 'abstain'),
        ('extra_evidence_field', json.dumps({**valid, 'evidence': [{'chunk_id': chunk_id, 'quote': good_quote, 'page': 1}]}), 'abstain'),
        ('quote_too_short', json.dumps({**valid, 'evidence': [{'chunk_id': chunk_id, 'quote': 'NASA'}]}), 'abstain'),
        ('fabricated_quote', json.dumps({**valid, 'evidence': [{'chunk_id': chunk_id, 'quote': 'NASA operates exactly forty-seven ocean buoys today'}]}), 'abstain'),
        ('unknown_chunk_id', json.dumps({**valid, 'evidence': [{'chunk_id': 'not-a-chunk:000999', 'quote': good_quote}]}), 'abstain'),
        ('quote_from_wrong_chunk', json.dumps({**valid, 'evidence': [{'chunk_id': other, 'quote': good_quote}]}) if other != chunk_id and good_quote not in documents[1].page_content else None, 'abstain'),
        ('abstained_true', json.dumps({'answer': 'Not sure.', 'abstained': True, 'evidence': []}), 'abstain'),
        ('empty_evidence', json.dumps({**valid, 'evidence': []}), 'abstain'),
        ('string_boolean', json.dumps({**valid, 'abstained': 'false'}), 'abstain'),
        ('truncated_json', json.dumps(valid)[:-5], 'abstain'),
    ]
    results = []
    for name, raw, expected in cases:
        if raw is None:
            continue
        out = validate_grounded_answer(raw, documents)
        outcome = 'abstain' if out['abstained'] else 'answer'
        passed = outcome == expected and (outcome == 'abstain' or all(c['text'].lower() == good_quote.lower() for c in out['citations']))
        results.append({'name': name, 'expected': expected, 'outcome': outcome, 'passed': passed})
    empty = validate_grounded_answer(json.dumps(valid), [])
    results.append({'name': 'empty_retrieval_context', 'expected': 'abstain',
                    'outcome': 'abstain' if empty['abstained'] else 'answer', 'passed': empty['abstained']})
    return results
