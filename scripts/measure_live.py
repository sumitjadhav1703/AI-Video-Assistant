"""Time a live deployment end to end from outside: probes, one upload, stage changes, questions, delete.

Usage: python scripts/measure_live.py <backend_url> <media_file> [--question Q ...]
Makes real provider calls on the target (one analysis, one call per question) and uses the caller's
daily allowance. Prints JSON to stdout. Never prints the job token, transcript or answer text.
"""
import argparse
import json
import mimetypes
import statistics
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_QUESTIONS = (
    'What is generative AI, according to the speaker?',
    'What examples of generated content are mentioned?',
    'Who won the 2022 FIFA World Cup?',  # not in the clip: the app should abstain
)
STEPS = ('queued', 'audio', 'transcript', 'title', 'summary', 'extract', 'rag', 'done')


def multipart(fields, file_field, filename, data):
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    ctype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                 f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + data + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'


def call(url, method='GET', body=None, headers=None, timeout=900):
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read()
    elapsed = round(time.perf_counter() - start, 3)
    try:
        parsed = json.loads(payload or b'null')
    except ValueError:
        parsed = None
    return status, elapsed, parsed


def summary(values):
    ordered = sorted(values)
    return {'n': len(ordered), 'min': ordered[0], 'p50': statistics.median(ordered),
            'p95': ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))], 'max': ordered[-1]}


def run(base, media, questions, poll_seconds=1.0, chat_gap=31.0):
    base = base.rstrip('/')
    out = {'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'backend': base}
    status, elapsed, _ = call(base + '/health', timeout=180)
    out['health_first'] = {'status': status, 'seconds': elapsed}
    ready = [call(base + '/ready')[1] for _ in range(10)]
    out['ready_10'] = summary(ready)
    out['demo_mode'] = call(base + '/demo-mode')[2]
    out['usage_before'] = (call(base + '/usage')[2] or {}).get('remaining')

    data = Path(media).read_bytes()
    body, ctype = multipart({'language': 'english', 'demo_acknowledged': 'true'}, 'file', Path(media).name, data)
    status, elapsed, job = call(base + '/jobs', 'POST', body, {'Content-Type': ctype})
    out['upload'] = {'status': status, 'seconds': elapsed, 'bytes': len(data)}
    if status != 200:
        out['upload']['detail'] = (job or {}).get('detail')
        return out
    job_id, auth = job['job_id'], {'Authorization': 'Bearer ' + job['job_token']}
    jobs = f'{base}/jobs/{job_id}'

    t0, last, transitions, polls = time.perf_counter(), None, [], []
    while True:
        status, elapsed, state = call(jobs, headers=auth, timeout=30)
        polls.append(elapsed)
        step = (state or {}).get('step') if status == 200 else f'http_{status}'
        if step != last:
            transitions.append({'step': step, 'at_seconds': round(time.perf_counter() - t0, 1)})
            last = step
        if (state or {}).get('status') in ('done', 'error', 'interrupted') or time.perf_counter() - t0 > 900:
            out['final_status'] = (state or {}).get('status')
            out['error'] = (state or {}).get('error')
            break
        time.sleep(poll_seconds)
    out['upload_to_done_seconds'] = round(time.perf_counter() - t0 + out['upload']['seconds'], 1)
    out['transitions'] = transitions
    out['status_poll'] = summary(polls)

    if out['final_status'] == 'done':
        status, elapsed, result = call(jobs + '/result', headers=auth)
        out['result'] = {'status': status, 'seconds': elapsed,
                         'chars': {k: len(v) for k, v in (result or {}).items() if isinstance(v, str) and k != 'job_id'}}
        out['chats'] = []
        for i, question in enumerate(questions):
            if i:
                time.sleep(chat_gap)  # stay under the 2-questions-per-minute limit
            body = json.dumps({'question': question, 'tier': 'economy'}).encode()
            status, elapsed, reply = call(jobs + '/chat', 'POST', body, {**auth, 'Content-Type': 'application/json'})
            reply = reply or {}
            out['chats'].append({'question': question, 'status': status, 'seconds': elapsed,
                                 'abstained': reply.get('abstained'), 'citations': len(reply.get('citations') or []),
                                 'answer_chars': len(reply.get('answer') or ''), 'model': reply.get('model'),
                                 'retrieval': reply.get('retrieval'), 'detail': reply.get('detail')})
    status, elapsed, _ = call(jobs, 'DELETE', headers=auth)
    out['delete'] = {'status': status, 'seconds': elapsed}
    out['usage_after'] = (call(base + '/usage')[2] or {}).get('remaining')
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('backend_url')
    parser.add_argument('media_file')
    parser.add_argument('--question', action='append', dest='questions')
    args = parser.parse_args(argv)
    print(json.dumps(run(args.backend_url, args.media_file, args.questions or DEFAULT_QUESTIONS), indent=2))


if __name__ == '__main__':
    sys.exit(main())
