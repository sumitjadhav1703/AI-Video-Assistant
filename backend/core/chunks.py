"""Build sanitized chunks with stable identity and honest time ranges."""
from langchain_core.documents import Document
from .guardrails import sanitize_text
from .llm_gateway import validate_transcript


def prepare_documents(segments, job_id):
    text = ' '.join(segment['text'].strip() for segment in segments if segment['text'].strip())
    validate_transcript(text)
    text = sanitize_text(text)
    ranges = []
    pos = 0
    for segment in segments:
        part = segment['text'].strip()
        if part:
            ranges.append((pos, pos + len(part), segment))
            pos += len(part) + 1
    docs = []
    for start in range(0, len(text), 450):
        # Fold a tail shorter than the overlap into this chunk instead of emitting a near-duplicate chunk.
        end = len(text) if len(text) - start <= 550 else start + 500
        covered = [s for left, right, s in ranges if left < end and right > start]
        if not covered:
            continue
        known = all(s['start_ms'] is not None and s['end_ms'] is not None for s in covered)
        precision = 'unknown' if not known or any(s['timing_precision'] == 'unknown' for s in covered) else ('piece' if any(s['timing_precision'] == 'piece' for s in covered) else 'segment')
        ordinal = len(docs)
        docs.append(Document(id=f'{job_id}:{ordinal:06d}', page_content=text[start:end], metadata={'job_id': job_id, 'ordinal': ordinal, 'chunk_index': ordinal, 'chunk_id': f'{job_id}:{ordinal:06d}', 'start_ms': min(s['start_ms'] for s in covered) if known else None, 'end_ms': max(s['end_ms'] for s in covered) if known else None, 'timing_precision': precision}))
        if end == len(text):
            break
    return docs
