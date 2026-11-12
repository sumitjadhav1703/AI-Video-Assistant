// Vite proxies /api during development. Production uses the public backend URL.
const ENV = import.meta.env || {};
const PROD_RAW = ENV.VITE_BACKEND_URL || '';
export const BACKEND_URL = ENV.PROD ? PROD_RAW.trim().replace(/\/+$/, '') : '/api';

const TIMEOUT = 180000;
// A 25 MiB upload on a slow link can outlast the read timeout.
const UPLOAD_TIMEOUT = 15 * 60 * 1000;
export const UPLOAD_TIMEOUT_HINT =
  'The upload timed out. The server may still be processing it, so wait a few minutes before uploading again.';
export const COLD_START_HINT =
  'The backend did not respond in time. The free instance may be waking up.';

export class BackendError extends Error {
  constructor(message, status = 0, retryAfterMs = 0) {
    super(message);
    this.status = status;
    this.retryAfterMs = retryAfterMs;
  }
}

async function callBackend(method, path, { body, headers, signal, valid, timeout = TIMEOUT, timeoutMessage = COLD_START_HINT } = {}) {
  if (!BACKEND_URL) throw new BackendError('Backend URL is not configured.');

  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  else signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, timeout);

  try {
    const response = await fetch(`${BACKEND_URL}${path}`, {
      method, body, headers, signal: controller.signal, cache: 'no-store', redirect: 'error',
    });
    const payload = await response.json().catch((error) => {
      if (controller.signal.aborted) throw error;
      return null;
    });
    if (response.status === 204) return {};
    if (response.ok) {
      if (payload && (!valid || valid(payload))) return payload;
      throw new BackendError('The backend returned an invalid response.', 502);
    }

    const retryAfter = [429, 503].includes(response.status) ? response.headers.get('Retry-After') : null;
    let retryAfterMs = 0;
    let message = typeof payload?.detail === 'string'
      ? payload.detail
      : `Backend returned ${response.status}.`;
    if (retryAfter) {
      retryAfterMs = /^\d+$/.test(retryAfter)
        ? Number(retryAfter) * 1000
        : Math.max(0, Date.parse(retryAfter) - Date.now()) || 0;
      if (retryAfterMs) message += ` Try again in ${Math.ceil(retryAfterMs / 1000)} seconds.`;
    }
    throw new BackendError(message, response.status, retryAfterMs);
  } catch (error) {
    if (signal?.aborted || error instanceof BackendError) throw error;
    if (error.name === 'AbortError') throw new BackendError(timeoutMessage);
    throw new BackendError(`Could not reach the backend. ${COLD_START_HINT}`);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

export const getDemoMode = (signal) => callBackend('GET', '/demo-mode', { signal });

export function startJob({ file, inviteCode, language = 'english' }) {
  const form = new FormData();
  form.append('file', file, file.name);
  form.append('language', language === 'hinglish' ? 'hinglish' : 'english');
  form.append('demo_acknowledged', 'true');
  const headers = inviteCode ? { 'X-Demo-Invite': inviteCode } : undefined;
  return callBackend('POST', '/jobs', { body: form, headers, timeout: UPLOAD_TIMEOUT, timeoutMessage: UPLOAD_TIMEOUT_HINT });
}

const jobPath = ({ id }) => `/jobs/${encodeURIComponent(id)}`;
const jobAuth = ({ token }) => ({ Authorization: `Bearer ${token}` });

export const getStatus = (job, signal) =>
  callBackend('GET', jobPath(job), { headers: jobAuth(job), signal });
const RESULT_FIELDS = ['title', 'summary', 'transcript', 'action_items', 'key_decisions', 'open_questions'];

export const getResult = (job, signal) =>
  callBackend('GET', `${jobPath(job)}/result`, {
    headers: jobAuth(job), signal,
    valid: (result) => RESULT_FIELDS.every((field) => typeof result[field] === 'string'),
  });

export const askChat = (job, question) =>
  callBackend('POST', `${jobPath(job)}/chat`, {
    body: JSON.stringify({ question, tier: 'economy' }),
    headers: { ...jobAuth(job), 'Content-Type': 'application/json' },
    valid: ({ answer, citations, model }) => typeof answer === 'string' && Array.isArray(citations)
      && citations.every((citation) => typeof citation?.chunk_id === 'string' && typeof citation?.text === 'string')
      && (model?.tier == null || typeof model.tier === 'string'),
  });

export const releaseJob = (job) => callBackend('DELETE', jobPath(job), { headers: jobAuth(job) });
