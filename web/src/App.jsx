import { useCallback, useEffect, useRef, useState } from 'react';
import DemoSample from './components/DemoSample';
import Empty from './components/Empty';
import Processing from './components/Processing';
import Results from './components/Results';
import { STEP_ORDER } from './lib/theme';
import { startJob, getDemoMode, getStatus, getResult, askChat, releaseJob } from './api';

const SESSION_KEY = 'minutes.live-session';
const POLL_WINDOW = 5 * 60 * 1000;
const READ_TIMEOUT = 20 * 1000;

function savedSession() {
  try {
    const value = JSON.parse(sessionStorage.getItem(SESSION_KEY));
    if (typeof value?.id === 'string' && value.id && typeof value.token === 'string' && value.token) {
      return { id: value.id, token: value.token };
    }
  } catch {
    // The app can continue in memory when storage is unavailable.
  }
  return null;
}

function saveSession(session) {
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // The active page can still use an in-memory session.
  }
}

const expired = (error) => error.status === 404 || error.status === 410;
const retryable = (error) => !error.status || error.status === 429 || error.status >= 500;
const EXPIRED_NOTICE = 'This live session has expired or is no longer available.';

export default function App() {
  const [session, setSession] = useState(savedSession);
  const [view, setView] = useState(() => session && window.history.state?.resumeLiveDemo ? 'session' : 'sample');
  const [mode, setMode] = useState('loading');
  const [modeAttempt, setModeAttempt] = useState(0);
  const [meta, setMeta] = useState({ language: 'english' });
  const [phase, setPhase] = useState('processing');
  const [stageIdx, setStageIdx] = useState(-1);
  const [result, setResult] = useState(null);
  const [chat, setChat] = useState([]);
  const [notice, setNotice] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [deleteError, setDeleteError] = useState('');
  const [pollNotice, setPollNotice] = useState('');
  const [checking, setChecking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const writes = useRef({ upload: false, chat: false, deletion: false });
  const pollTiming = useRef({ start: 0, retryAt: 0 });
  const checkStatus = useRef(null);

  useEffect(() => {
    window.history.replaceState({
      ...window.history.state,
      resumeLiveDemo: view === 'session' && Boolean(session),
    }, '');
  }, [view, session]);

  const openView = (nextView) => {
    if (nextView === 'live' && view !== 'live' && !session) setMode('loading');
    setView(nextView);
    window.scrollTo({ top: 0, behavior: 'instant' });
  };

  const clearSession = useCallback((message) => {
    saveSession(null);
    setSession(null);
    setResult(null);
    setChat([]);
    setStageIdx(-1);
    setPhase('processing');
    setDeleteError('');
    setPollNotice('');
    pollTiming.current = { start: 0, retryAt: 0 };
    setNotice(message);
    setView((current) => current === 'session' ? 'live' : current);
  }, []);

  useEffect(() => {
    if (view !== 'live' || session) return;
    const controller = new AbortController();
    setMode('loading');
    getDemoMode(controller.signal).then(({ mode: availableMode }) => {
      if (controller.signal.aborted) return;
      setMode(['sample', 'invited', 'public'].includes(availableMode) ? availableMode : 'unavailable');
    }).catch(() => {
      if (!controller.signal.aborted) setMode('unavailable');
    });
    return () => controller.abort();
  }, [view, session, modeAttempt]);

  useEffect(() => {
    if (view !== 'session' || !session || phase !== 'processing' || deleting) return;
    const timing = pollTiming.current;
    timing.start ||= Date.now();
    const deadline = timing.start + POLL_WINDOW;
    let controller;
    let timeout;
    let disposed = false;
    let pausedRequest;
    let recheck = false;
    setChecking(false);

    const schedule = () => {
      if (disposed || document.hidden) return;
      const now = Date.now();
      const cadence = now - timing.start < 30000 ? 3000 : 5000;
      const next = Math.max(now + cadence, timing.retryAt);
      clearTimeout(timeout);
      if (next >= deadline) {
        setPollNotice((message) => message
          ? `${message} Automatic checks have paused.`
          : 'Automatic checks have paused. Use Check status to try again.');
        return;
      }
      timeout = setTimeout(() => read(), next - now);
    };

    const read = async (manual = false) => {
      if (disposed || document.hidden || controller) return;
      const remaining = deadline - Date.now();
      if (!manual && remaining <= 0) {
        setPollNotice('Automatic checks have paused. Use Check status to try again.');
        return;
      }
      if (Date.now() < timing.retryAt) {
        if (!manual) schedule();
        else setPollNotice(`Try again in ${Math.ceil((timing.retryAt - Date.now()) / 1000)} seconds.`);
        return;
      }
      clearTimeout(timeout);
      const request = new AbortController();
      controller = request;
      const timer = setTimeout(() => request.abort(), manual ? READ_TIMEOUT : Math.min(READ_TIMEOUT, remaining));
      setChecking(true);
      let again = false;
      try {
        const status = await getStatus(session, request.signal);
        if (disposed || request.signal.aborted) return;
        if (status.status === 'done') {
          const response = await getResult(session, request.signal);
          if (disposed || request.signal.aborted) return;
          setResult(response);
          setPollNotice('');
          setPhase('ready');
        } else if (status.status === 'error' || status.status === 'interrupted') {
          setPollNotice(status.error || 'The analysis stopped. Delete the session to start again.');
          setPhase('error');
        } else {
          const index = STEP_ORDER.indexOf(status.step);
          if (index >= 0) setStageIdx(index);
          setPollNotice(manual && Date.now() >= deadline ? 'The clip is still processing. You can check again.' : '');
          again = true;
        }
      } catch (error) {
        if (disposed || document.hidden || pausedRequest === request) return;
        if (expired(error)) clearSession(EXPIRED_NOTICE);
        else if (retryable(error)) {
          if (error.retryAfterMs) timing.retryAt = Date.now() + error.retryAfterMs;
          setPollNotice(request.signal.aborted ? 'The status check timed out.' : error.message);
          again = true;
        } else {
          setPollNotice(error.message);
        }
      } finally {
        clearTimeout(timer);
        controller = undefined;
        if (!disposed) {
          setChecking(false);
          if (recheck) {
            recheck = false;
            read();
          } else if (again && (!manual || Date.now() < deadline)) schedule();
        }
      }
    };

    const onVisibility = () => {
      clearTimeout(timeout);
      if (document.hidden) {
        pausedRequest = controller;
        controller?.abort();
      } else if (controller === pausedRequest && controller) {
        recheck = true;
      } else {
        read();
      }
    };

    checkStatus.current = () => read(true);
    document.addEventListener('visibilitychange', onVisibility);
    read();
    return () => {
      disposed = true;
      checkStatus.current = null;
      clearTimeout(timeout);
      controller?.abort();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [view, session, phase, deleting, clearSession]);

  const analyse = async ({ file, inviteCode }) => {
    if (writes.current.upload || session || !['invited', 'public'].includes(mode)) return;
    writes.current.upload = true;
    setNotice('');
    setUploadError('');
    setSubmitting(true);
    try {
      const { job_id: id, job_token: token } = await startJob({ file, inviteCode });
      if (typeof id !== 'string' || !id || typeof token !== 'string' || !token) {
        throw new Error('The backend did not return a usable session.');
      }
      const created = { id, token };
      saveSession(created);
      setMeta({ fileName: file.name, fileSize: file.size, language: 'english' });
      setSession(created);
      setPhase('processing');
      setView((current) => current === 'live' ? 'session' : current);
    } catch (error) {
      setUploadError(error.message);
    } finally {
      writes.current.upload = false;
      setSubmitting(false);
    }
  };

  const ask = async (question) => {
    if (!session || writes.current.chat || writes.current.deletion) return;
    writes.current.chat = true;
    const id = Date.now();
    setChat((messages) => [...messages, { id, q: question, a: '', pending: true }]);
    try {
      const response = await askChat(session, question);
      setChat((messages) => messages.map((message) => message.id === id
        ? { ...message, a: response.answer, citations: response.citations, model: response.model, retrieval: response.retrieval, pending: false }
        : message));
    } catch (error) {
      if (expired(error)) clearSession(EXPIRED_NOTICE);
      else setChat((messages) => messages.map((message) => message.id === id
        ? { ...message, a: error.message, pending: false }
        : message));
    } finally {
      writes.current.chat = false;
    }
  };

  const remove = async () => {
    if (!session || writes.current.deletion || writes.current.chat) return;
    writes.current.deletion = true;
    setDeleting(true);
    setDeleteError('');
    try {
      const response = await releaseJob(session);
      if (response.deleted !== true) throw new Error('The backend did not confirm deletion.');
      clearSession('Live session deleted.');
    } catch (error) {
      if (expired(error)) clearSession(EXPIRED_NOTICE);
      else setDeleteError(`Could not delete the live session. ${error.message} Your session is still available in this tab.`);
    } finally {
      writes.current.deletion = false;
      setDeleting(false);
    }
  };

  return (
    <>
      <header className="demo-header">
        <span className="demo-brand">Minutes</span>
        <nav aria-label="Demo paths" className="demo-paths">
          <button type="button" className="demo-button" aria-pressed={view === 'sample'}
            onClick={() => openView('sample')}>Explore a sample</button>
          <button type="button" className="demo-button" aria-pressed={view === 'live' || view === 'session'}
            onClick={() => view !== 'session' && openView('live')}>Analyze your own clip</button>
        </nav>
      </header>
      <main>
        {view === 'home' && (
          <section className="demo-panel">
            <h1>Video and meeting analysis</h1>
            <p>Read a summary and ask questions with timestamp citations.</p>
          </section>
        )}
        {(view === 'home' || view === 'sample' || view === 'live') && session && (
          <div className="demo-panel demo-resume">
            <button className="demo-button" onClick={() => { setPhase('processing'); openView('session'); }}>Resume live session</button>
          </div>
        )}
        {view === 'sample' && <DemoSample onBack={() => openView('home')} />}
        {notice && <p className="demo-panel demo-feedback" role="status">{notice}</p>}
        {view === 'live' && !session && (
          <>
            {mode === 'loading' && <p className="demo-panel" role="status">Checking live availability. The backend may be waking up.</p>}
            {mode === 'sample' && (
              <section className="demo-panel">
                <h1>Live analysis is paused</h1>
                <p>Explore the prepared sample for a summary, transcript, and timestamped answers.</p>
                <button className="demo-button" onClick={() => openView('sample')}>Open sample</button>
              </section>
            )}
            {mode === 'unavailable' && (
              <section className="demo-panel">
                <h1>Live analysis is unavailable</h1>
                <p role="status">Could not check live availability. The sample is ready to explore.</p>
                <button className="demo-button" onClick={() => setModeAttempt((attempt) => attempt + 1)}>Check availability</button>
              </section>
            )}
            {(mode === 'invited' || mode === 'public') &&
              <Empty mode={mode} submitting={submitting} onAnalyse={analyse} />}
            {uploadError && <p className="demo-panel demo-feedback" role="alert">{uploadError}</p>}
          </>
        )}
        {view === 'session' && session && (
          <>
            <section className="demo-panel demo-session" aria-label="Live session controls">
              <div className="demo-paths">
                {phase === 'processing' && (
                  <button className="demo-button" disabled={checking || deleting} onClick={() => checkStatus.current?.()}>
                    {checking ? 'Checking status…' : 'Check status'}
                  </button>
                )}
                <button className="demo-button" disabled={deleting || chat.some((message) => message.pending)} onClick={remove}>
                  {deleting ? 'Deleting session…' : 'Delete session'}
                </button>
              </div>
              {deleteError && <p role="alert">{deleteError}</p>}
              {pollNotice && <p role="status">{pollNotice}</p>}
            </section>
            {phase === 'processing' && <Processing fileName={meta.fileName || 'Live clip'} stageIdx={stageIdx} />}
            {phase === 'ready' && result && (
              <Results result={result} meta={meta} chat={chat} onAsk={ask} mode="live" economyOnly />
            )}
            {phase === 'error' && <h1 className="demo-panel">Analysis stopped</h1>}
          </>
        )}
      </main>
    </>
  );
}
