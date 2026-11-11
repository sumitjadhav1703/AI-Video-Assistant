import test from 'node:test';
import assert from 'node:assert/strict';
import { askChat, getDemoMode, getStatus, getResult, releaseJob, startJob } from './api.js';

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

test('every job operation uses bearer auth and chat sends economy', async () => {
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, ...options });
    return new Response('{}');
  };
  await getStatus(job);
  await getResult(job);
  await askChat(job, 'question', 'strong');
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
