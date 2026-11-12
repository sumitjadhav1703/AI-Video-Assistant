import test from 'node:test';
import assert from 'node:assert/strict';
import { askChat, getDemoMode, getStatus, getResult, releaseJob, startJob, UPLOAD_TIMEOUT_HINT } from './api.js';

const job = { id: 'job', token: 'capability-secret' };

test('rate limit exposes Retry-After and does not retry a chat write', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response(JSON.stringify({ detail: 'Daily limit reached.' }), {
      status: 429, headers: { 'Retry-After': '42', 'Content-Type': 'application/json' },
    });
  };
  await assert.rejects(askChat(job, 'question'), (error) =>
    error.status === 429 && error.retryAfterMs === 42000 && /Daily limit reached.*42/.test(error.message));
  assert.equal(calls, 1);
});

test('status handles date-form Retry-After and has no implicit retries', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response('{}', {
      status: 429, headers: { 'Retry-After': new Date(Date.now() + 30000).toUTCString() },
    });
  };
  await assert.rejects(getStatus(job), (error) => error.retryAfterMs > 28000 && error.retryAfterMs <= 30000);
  assert.equal(calls, 1);
});

test('unavailable backend reports its detail and does not retry', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response(JSON.stringify({ detail: 'Provider disabled.' }), { status: 503 });
  };
  await assert.rejects(askChat(job, 'question'), /Provider disabled/);
  assert.equal(calls, 1);
});

test('availability is unauthenticated and invite is sent only on an invited upload', async () => {
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, ...options });
    return new Response('{}');
  };
  const file = Object.assign(new Blob(['clip'], { type: 'audio/wav' }), { name: 'clip.wav' });
  await getDemoMode();
  await startJob({ file, inviteCode: 'invitation' });
  await startJob({ file });
  assert.ok(requests[0].url.endsWith('/demo-mode'));
  assert.equal(requests[0].headers, undefined);
  assert.deepEqual(requests[1].headers, { 'X-Demo-Invite': 'invitation' });
  assert.equal(requests[2].headers, undefined);
  const form = requests[1].body;
  assert.deepEqual([...form.keys()], ['file', 'language', 'demo_acknowledged']);
  assert.equal(form.get('language'), 'english');
  assert.equal(form.get('demo_acknowledged'), 'true');
});

test('upload sends hinglish only when chosen and never an arbitrary language', async () => {
  const forms = [];
  globalThis.fetch = async (url, options) => {
    forms.push(options.body);
    return new Response('{}');
  };
  const file = Object.assign(new Blob(['clip'], { type: 'audio/wav' }), { name: 'clip.wav' });
  await startJob({ file, language: 'hinglish' });
  await startJob({ file, language: 'klingon' });
  assert.equal(forms[0].get('language'), 'hinglish');
  assert.equal(forms[1].get('language'), 'english');
});

test('every job operation uses bearer auth and chat sends economy', async () => {
  const requests = [];
  const result = { title: 'Title', summary: 'Summary', transcript: 'Transcript',
    action_items: '', key_decisions: '', open_questions: '' };
  globalThis.fetch = async (url, options) => {
    requests.push({ url, ...options });
    if (url.endsWith('/result')) return Response.json(result);
    if (url.endsWith('/chat')) return Response.json({ answer: 'Answer', citations: [] });
    return new Response('{}');
  };
  await getStatus(job);
  await getResult(job);
  await askChat(job, 'question');
  await releaseJob(job);
  assert.deepEqual(requests.map(({ method, url }) => [method, new URL(url, 'http://localhost').pathname]), [
    ['GET', '/api/jobs/job'], ['GET', '/api/jobs/job/result'], ['POST', '/api/jobs/job/chat'], ['DELETE', '/api/jobs/job'],
  ]);
  for (const { headers, url } of requests) {
    assert.equal(headers.Authorization, 'Bearer capability-secret');
    assert.equal(url.includes(job.token), false);
    assert.equal(headers['X-Demo-Invite'], undefined);
  }
  assert.equal(JSON.parse(requests[2].body).tier, 'economy');
});

test('malformed successful results and chat responses are rejected before rendering', async () => {
  for (const [call, body] of [
    [() => getResult(job), { title: 'Title', summary: { body: 'Wrong shape' } }],
    [() => askChat(job, 'question'), { answer: 'Answer', citations: 'Wrong shape' }],
    [() => askChat(job, 'question'), { answer: 'Answer', citations: [null] }],
  ]) {
    globalThis.fetch = async () => Response.json(body);
    await assert.rejects(call(), (error) =>
      error.status === 502 && /invalid response/i.test(error.message));
  }
});

test('credentialed API requests reject redirects instead of forwarding headers', async () => {
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push(options);
    return Response.json({});
  };
  const file = Object.assign(new Blob(['clip']), { name: 'clip.wav' });
  await startJob({ file, inviteCode: 'invitation' });
  assert.equal(requests[0].redirect, 'error');
});

test('503 exposes Retry-After like 429', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Busy.' }), {
    status: 503, headers: { 'Retry-After': '7' },
  });
  await assert.rejects(getStatus(job), (error) =>
    error.status === 503 && error.retryAfterMs === 7000 && /Busy.*7 seconds/.test(error.message));
});

test('an empty 204 response is a success', async () => {
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.deepEqual(await releaseJob(job), {});
});

test('a timed-out upload warns that the job may still exist', async () => {
  globalThis.fetch = async () => { throw new DOMException('aborted', 'AbortError'); };
  const file = Object.assign(new Blob(['clip']), { name: 'clip.wav' });
  await assert.rejects(startJob({ file }), (error) => error.message === UPLOAD_TIMEOUT_HINT);
});
