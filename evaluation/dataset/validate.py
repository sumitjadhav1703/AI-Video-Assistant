"""Validate the golden set against the source transcript and derive chunk ids and timestamps.

Run: python -m evaluation.dataset.validate          (writes goldens_resolved.jsonl)
     python -m evaluation.dataset.validate --check  (fails if the resolved file is stale)
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from evaluation import config
from evaluation.dataset import build_chunks

GOLDENS_FILE = build_chunks.DATASET_DIR / 'goldens.jsonl'
RESOLVED_FILE = build_chunks.DATASET_DIR / 'goldens_resolved.jsonl'
VERIFICATION = {'method': 'exact-substring check against the source captions + author review',
                'author': 'claude-opus-5-5', 'human_review': 'pending'}

Behavior = Literal['answer', 'abstain', 'answer_or_abstain', 'correct_premise_or_abstain']
Category = Literal[tuple(config.CATEGORY_COUNTS)]


class Golden(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^NASA-[A-Z]-\d{3}$')
    category: Category
    question: str = Field(min_length=5)
    expected_answer: str = Field(min_length=5)
    relevant_facts: list[str]
    expected_evidence: list[str]
    expected_behavior: Behavior
    absent_terms: list[str] = []
    premise_correction_terms: list[str] = []
    notes: str = ''


def load_goldens(path=GOLDENS_FILE):
    goldens = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if line.strip():
            try:
                goldens.append(Golden.model_validate_json(line))
            except ValidationError as error:
                raise ValueError(f'{path}:{number}: {error}') from None
    return goldens


def _segment_ranges(segments):
    ranges, pos = [], 0
    for segment in segments:
        part = segment['text'].strip()
        if part:
            ranges.append((pos, pos + len(part), segment))
            pos += len(part) + 1
    return ranges


def resolve(goldens, segments, documents):
    """Check every record; return (resolved records, errors). Never raises on data problems."""
    text = build_chunks.transcript_text(segments)
    raw = ' '.join(s['text'].strip() for s in segments if s['text'].strip())
    errors = []
    if raw != text:
        errors.append('Sanitization changed the transcript; character offsets would not map to cues.')
    ranges = _segment_ranges(segments)
    counts = Counter(g.category for g in goldens)
    if dict(counts) != config.CATEGORY_COUNTS:
        errors.append(f'Category counts {dict(counts)} differ from the design {config.CATEGORY_COUNTS}.')
    ids = Counter(g.id for g in goldens)
    errors += [f'Duplicate id {i}' for i, n in ids.items() if n > 1]
    lowered = text.lower()
    resolved = []
    for g in goldens:
        where = g.id
        if g.id.split('-')[1] != config.CATEGORY_PREFIX[g.category]:
            errors.append(f'{where}: id prefix does not match category {g.category}')
        if g.expected_behavior != config.CATEGORY_BEHAVIOR[g.category]:
            errors.append(f'{where}: behavior {g.expected_behavior} does not match category {g.category}')
        evidence = []
        if g.expected_behavior == 'abstain':
            if g.expected_evidence or g.relevant_facts:
                errors.append(f'{where}: unanswerable items carry no evidence or facts')
            if not g.absent_terms:
                errors.append(f'{where}: unanswerable items need absent_terms')
            errors += [f'{where}: absent term {t!r} appears in the transcript' for t in g.absent_terms if t.lower() in lowered]
        else:
            if not g.expected_evidence:
                errors.append(f'{where}: answerable items need evidence')
            for quote in g.expected_evidence:
                if len(quote.split()) < config.MIN_QUOTE_WORDS or len(quote) < config.MIN_QUOTE_CHARS:
                    errors.append(f'{where}: quote too short for the app grounding rule: {quote!r}')
                start = text.find(quote)
                if start < 0:
                    errors.append(f'{where}: quote is not an exact substring of the transcript: {quote!r}')
                    continue
                if text.find(quote, start + 1) >= 0:
                    errors.append(f'{where}: quote is not unique in the transcript: {quote!r}')
                end = start + len(quote)
                chunk_ids = [d.metadata['chunk_id'] for d in documents if quote in d.page_content]
                if not chunk_ids:
                    errors.append(f'{where}: quote spans a chunk boundary and cannot be cited: {quote!r}')
                cues = [s for left, right, s in ranges if left < end and right > start]
                evidence.append({'quote': quote, 'chunk_ids': chunk_ids,
                                 'start_ms': min(s['start_ms'] for s in cues), 'end_ms': max(s['end_ms'] for s in cues)})
        if g.expected_behavior == 'correct_premise_or_abstain':
            if not g.premise_correction_terms:
                errors.append(f'{where}: misleading items need premise_correction_terms')
            elif not any(t.lower() in q.lower() for t in g.premise_correction_terms for q in g.expected_evidence):
                errors.append(f'{where}: no premise correction term is supported by the evidence')
        gold = sorted({c for e in evidence for c in e['chunk_ids']})
        resolved.append({**g.model_dump(), 'source_id': build_chunks.SOURCE_ID, 'job_id': build_chunks.JOB_ID,
                         'gold_chunk_ids': gold, 'evidence': evidence, 'verification': VERIFICATION})
    return resolved, errors


def _serialize(records):
    return ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail if goldens_resolved.jsonl is stale')
    args = parser.parse_args(argv)
    segments = build_chunks.load_segments()
    documents = build_chunks.build_documents(segments)
    resolved, errors = resolve(load_goldens(), segments, documents)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    content = _serialize(resolved)
    if args.check:
        if not RESOLVED_FILE.exists() or RESOLVED_FILE.read_text() != content:
            print('goldens_resolved.jsonl is stale; run python -m evaluation.dataset.validate', file=sys.stderr)
            return 1
    else:
        RESOLVED_FILE.write_text(content)
    counts = Counter(r['category'] for r in resolved)
    print(f'{len(resolved)} goldens valid ({dict(counts)}); '
          f'{sum(len(r["evidence"]) for r in resolved)} evidence quotes verified -> {RESOLVED_FILE.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
