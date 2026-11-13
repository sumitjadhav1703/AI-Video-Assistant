"""Parse the public-domain captions and chunk them with the application's own chunker.

Run: python -m evaluation.dataset.build_chunks   (writes evaluation/dataset/chunks.jsonl)
"""
import hashlib
import json
import re
from pathlib import Path

from backend.core.chunks import prepare_documents
from backend.core.guardrails import sanitize_text

DATASET_DIR = Path(__file__).resolve().parent
SOURCE_ID = 'nasa-cop26-stgermain'
SOURCE_FILE = DATASET_DIR / 'source' / 'nasa_cop26_stgermain.en_US.vtt'
SOURCE_SHA256 = 'df3327e672b85cbbbe35f1949b68f94de52ba5538a2cee64316abe70dcc55c6b'
CHUNKS_FILE = DATASET_DIR / 'chunks.jsonl'
# The API only accepts 32-hex job ids; derive a stable one from the source id.
JOB_ID = hashlib.sha256(SOURCE_ID.encode()).hexdigest()[:32]

_STAMP = re.compile(r'(\d+):(\d{2}):(\d{2})\.(\d{3})')


def _ms(stamp):
    hours, minutes, seconds, millis = map(int, _STAMP.fullmatch(stamp).groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_vtt(text):
    """WebVTT cues -> the segment shape produced by backend.core.transcriber."""
    segments = []
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n')):
        lines = [line.strip() for line in block.strip().split('\n') if line.strip()]
        timing = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if timing is None:
            continue
        start, end = (part.strip().split()[0] for part in lines[timing].split('-->'))
        cue = ' '.join(lines[timing + 1:]).strip()
        if cue:
            segments.append({'text': cue, 'start_ms': _ms(start), 'end_ms': _ms(end), 'timing_precision': 'segment'})
    return segments


def load_segments(path=SOURCE_FILE, sha256=SOURCE_SHA256):
    data = Path(path).read_bytes()
    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f'{path} does not match the recorded SHA-256; the source changed.')
    return parse_vtt(data.decode('utf-8'))


def transcript_text(segments):
    """The sanitized transcript exactly as backend.jobs.run_job and prepare_documents see it."""
    return sanitize_text(' '.join(s['text'].strip() for s in segments if s['text'].strip()))


def build_documents(segments=None, job_id=JOB_ID):
    return prepare_documents(segments if segments is not None else load_segments(), job_id)


def chunk_records(documents):
    return [{'chunk_id': d.metadata['chunk_id'], 'ordinal': d.metadata['ordinal'],
             'start_ms': d.metadata['start_ms'], 'end_ms': d.metadata['end_ms'],
             'timing_precision': d.metadata['timing_precision'], 'chars': len(d.page_content),
             'sha256': hashlib.sha256(d.page_content.encode()).hexdigest(), 'text': d.page_content}
            for d in documents]


def main():
    records = chunk_records(build_documents())
    CHUNKS_FILE.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
    print(f'{len(records)} chunks for job {JOB_ID} -> {CHUNKS_FILE}')


if __name__ == '__main__':
    main()
