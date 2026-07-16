// Single funnel for every backend call. The backend URL is public (a Render
// HTTPS endpoint), never a secret.
//
// In dev, calls go to the same-origin `/api` path, which the Vite dev server
// proxies to the backend server-side — this sidesteps CORS so `npm run dev`
// works against the deployed backend without adding localhost to the backend's
// allow-list. In production the app talks to the backend directly via
// VITE_BACKEND_URL (the Vercel origin is authorized on the backend instead).
const PROD_RAW = import.meta.env.VITE_BACKEND_URL || 'https://ai-video-assistant-backend.onrender.com';
export const BACKEND_URL = import.meta.env.DEV ? '/api' : PROD_RAW.replace(/\/+$/, '');

// Render's free tier spins down after 15 min idle and can take ~60s to wake.
// Every call gets a generous timeout so a cold start reads as "waking up".
const TIMEOUT = 180000;
export const COLD_START_HINT =
  "The backend didn't respond in time. On Render's free tier it spins down after " +
  '15 minutes idle and takes up to a minute to wake up. Give it a moment and try again.';

export class BackendError extends Error {}

async function callBackend(method, path, { body, headers } = {}) {
  if (!BACKEND_URL) throw new BackendError('Backend URL is not configured.');

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT);

  let res;
  try {
    res = await fetch(`${BACKEND_URL}${path}`, { method, body, headers, signal: controller.signal });
  } catch (err) {
    clearTimeout(timer);
    if (err.name === 'AbortError') throw new BackendError(COLD_START_HINT);
    throw new BackendError(`Could not reach the backend. ${COLD_START_HINT}`);
  }
  clearTimeout(timer);

  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = null;
    }
    throw new BackendError(detail || `Backend returned ${res.status}.`);
  }
  return res.json();
}

// Start a run — either an uploaded file or a YouTube URL, plus the language.
// Returns { job_id, status }. The pipeline runs in the background on the backend.
export function startJob({ file, youtubeUrl, language }) {
  const form = new FormData();
  form.append('language', language);
  if (file) form.append('file', file, file.name);
  else form.append('youtube_url', youtubeUrl);
  return callBackend('POST', '/jobs', { body: form });
}

export const getStatus = (jobId) => callBackend('GET', `/jobs/${jobId}`);
export const getResult = (jobId) => callBackend('GET', `/jobs/${jobId}/result`);

export const askChat = (jobId, question) =>
  callBackend('POST', `/jobs/${jobId}/chat`, {
    body: JSON.stringify({ question }),
    headers: { 'Content-Type': 'application/json' },
  });

export const releaseJob = (jobId) => callBackend('DELETE', `/jobs/${jobId}`);

// Fire-and-forget release for tab close / refresh. `keepalive` lets the request
// outlive the page during unload (where a normal awaited fetch would be killed),
// so the job's DB row + vectors get dropped instead of orphaned in Neon.
export function releaseJobOnUnload(jobId) {
  if (!jobId || !BACKEND_URL) return;
  try {
    fetch(`${BACKEND_URL}/jobs/${jobId}`, { method: 'DELETE', keepalive: true });
  } catch {
    /* best-effort — nothing we can do as the page goes away */
  }
}
