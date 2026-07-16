import { useCallback, useEffect, useRef, useState } from 'react';
import Overlays from './components/Overlays';
import Nav from './components/Nav';
import Preloader from './components/Preloader';
import Empty from './components/Empty';
import Processing from './components/Processing';
import Results from './components/Results';
import { SANS, MONO, CREAM, SUBTLE, MUTE, DIM, STEP_ORDER } from './lib/theme';
import { startJob, getStatus, getResult, askChat, releaseJob, releaseJobOnUnload, BackendError } from './api';
import { sleep } from './lib/parse';

export default function App() {
  const [phase, setPhase] = useState('boot'); // boot | empty | processing | ready | error
  const [job, setJob] = useState(null); // { id, fileName, fileSize, language }
  const [stageIdx, setStageIdx] = useState(-1);
  const [result, setResult] = useState(null);
  const [chat, setChat] = useState([]);
  const [errorMsg, setErrorMsg] = useState('');

  // A run token: incremented on each analyse/reset so a stale poll loop from a
  // previous run stops touching state once the user has moved on.
  const runRef = useRef(0);

  // Track the active job id in a ref so the unload handler (registered once) can
  // read the current value without re-binding. On tab close / refresh we release
  // the job so its DB row + vectors don't orphan in Neon — the "New session"
  // button already handles the in-app case.
  const jobIdRef = useRef(null);
  useEffect(() => {
    jobIdRef.current = job?.id ?? null;
  }, [job]);
  useEffect(() => {
    const handler = () => releaseJobOnUnload(jobIdRef.current);
    window.addEventListener('pagehide', handler);
    return () => window.removeEventListener('pagehide', handler);
  }, []);

  const poll = useCallback(async (jobId, runId) => {
    while (runRef.current === runId) {
      const s = await getStatus(jobId);
      if (runRef.current !== runId) return;
      if (s.status === 'error') throw new BackendError(s.error || 'Processing failed.');
      if (s.status === 'done') break;
      const idx = STEP_ORDER.indexOf(s.step);
      if (idx >= 0) setStageIdx(idx);
      await sleep(3000);
    }
    if (runRef.current !== runId) return;
    setStageIdx(6);
    const r = await getResult(jobId);
    if (runRef.current !== runId) return;
    setResult(r);
    setPhase('ready');
  }, []);

  const analyse = useCallback(
    async ({ file, youtubeUrl, language }) => {
      const runId = (runRef.current += 1);
      const meta = {
        fileName: file ? file.name : youtubeUrl,
        fileSize: file ? file.size : null,
        language,
      };
      setErrorMsg('');
      setResult(null);
      setChat([]);
      setStageIdx(0);
      setJob({ id: null, ...meta });
      setPhase('processing');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      try {
        const { job_id: jobId } = await startJob({ file, youtubeUrl, language });
        if (runRef.current !== runId) return;
        setJob({ id: jobId, ...meta });
        await poll(jobId, runId);
      } catch (e) {
        if (runRef.current !== runId) return;
        setErrorMsg(e instanceof BackendError ? e.message : String(e));
        setPhase('error');
      }
    },
    [poll],
  );

  const ask = useCallback(
    async (question) => {
      if (!job?.id) return;
      const id = `${Date.now()}-${Math.random()}`;
      setChat((c) => [...c, { id, q: question, a: '', pending: true }]);
      try {
        const { answer } = await askChat(job.id, question);
        setChat((c) => c.map((m) => (m.id === id ? { ...m, a: answer, pending: false } : m)));
      } catch (e) {
        const msg = e instanceof BackendError ? e.message : String(e);
        setChat((c) => c.map((m) => (m.id === id ? { ...m, a: `⚠ ${msg}`, pending: false } : m)));
      }
    },
    [job],
  );

  const reset = useCallback(async () => {
    runRef.current += 1; // stop any in-flight poll
    const id = job?.id;
    setPhase('empty');
    setJob(null);
    setResult(null);
    setChat([]);
    setStageIdx(-1);
    setErrorMsg('');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (id) {
      try {
        await releaseJob(id);
      } catch {
        /* best-effort release */
      }
    }
  }, [job]);

  const navStatus =
    phase === 'processing' ? 'Processing…' : phase === 'ready' ? 'Session active' : 'No active session';

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', overflowX: 'clip' }}>
      <Overlays />
      {phase === 'boot' && <Preloader onDone={() => setPhase('empty')} />}
      <Nav
        status={navStatus}
        dotActive={phase === 'ready'}
        dotPulse={phase === 'processing'}
        showReset={phase === 'ready' || phase === 'error'}
        onReset={reset}
      />

      <main style={{ flex: 1, position: 'relative', zIndex: 4, paddingTop: 90 }}>
        {phase === 'empty' && <Empty onAnalyse={analyse} />}
        {phase === 'processing' && <Processing fileName={job?.fileName} stageIdx={stageIdx} />}
        {phase === 'ready' && result && (
          <Results result={result} meta={job} chat={chat} onAsk={ask} />
        )}
        {phase === 'error' && (
          <section
            style={{
              minHeight: 'calc(100vh - 260px)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              padding: '8vh 44px',
              maxWidth: 760,
              margin: '0 auto',
            }}
          >
            <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: MUTE, marginBottom: 24 }}>
              Something interrupted the run
            </div>
            <h1
              style={{
                margin: '0 0 28px',
                fontFamily: SANS,
                fontWeight: 500,
                fontSize: 'clamp(34px,5vw,64px)',
                lineHeight: 1.05,
                letterSpacing: '-0.03em',
              }}
            >
              It didn’t go through.
            </h1>
            <p style={{ margin: '0 0 40px', fontSize: 15, lineHeight: 1.75, color: SUBTLE }}>{errorMsg}</p>
            <button
              data-hov="1"
              data-mag="1"
              onClick={reset}
              style={{
                alignSelf: 'flex-start',
                background: CREAM,
                color: '#0e0e0d',
                border: '1.5px solid #e8e5de',
                fontFamily: MONO,
                fontSize: 12,
                letterSpacing: '0.06em',
                padding: '18px 40px',
                borderRadius: 14,
                boxShadow: '6px 6px 0 rgba(232,229,222,0.25)',
                transition: 'transform .3s cubic-bezier(.22,1,.36,1), box-shadow .2s',
              }}
            >
              Start over&nbsp;&nbsp;→
            </button>
          </section>
        )}
      </main>

      <footer style={{ borderTop: '1px solid rgba(232,229,222,0.10)', position: 'relative', zIndex: 4 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            padding: '22px 44px',
            fontFamily: MONO,
            fontSize: 10,
            letterSpacing: '0.2em',
            color: DIM,
            flexWrap: 'wrap',
            gap: 12,
          }}
        >
          <span>© 2026 Minutes</span>
          <span>Upload · transcribe · ask</span>
          <span>Every word, remembered</span>
        </div>
        <div style={{ overflow: 'hidden', padding: '0 32px' }}>
          <div
            style={{
              fontFamily: SANS,
              fontWeight: 300,
              fontSize: 'clamp(100px,17vw,280px)',
              lineHeight: 0.72,
              letterSpacing: '-0.04em',
              color: 'rgba(232,229,222,0.92)',
              transform: 'translateY(14%)',
              whiteSpace: 'nowrap',
              textAlign: 'center',
            }}
          >
            Minutes
          </div>
        </div>
      </footer>
    </div>
  );
}
