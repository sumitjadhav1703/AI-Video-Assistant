import { useEffect, useRef, useState } from 'react';
import { SANS, MONO, CREAM, SUBTLE, MUTE } from '../lib/theme';
import { humanSize } from '../lib/parse';

const ACCEPT = '.mp3,.wav,.m4a,.mp4,.mov,.mkv,.webm,.aac,.ogg,.flac';
const HERO_WORDS = ['remembered.', 'recorded.', 'summarised.', 'answered.', 'searchable.'];
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const DEMO_CLIPS = [
  { title: 'Onboarding pilot review', filename: 'onboarding-pilot.mp4' },
  { title: 'Release readiness review', filename: 'release-readiness.mp4' },
];
const noteStyle = { margin: '14px 2px 0', fontFamily: MONO, fontSize: 11, lineHeight: 1.7, color: MUTE };

export default function Empty({ mode, submitting, onAnalyse, onRetryAvailability, uploadError, notice }) {
  const [file, setFile] = useState(null);
  const [inviteCode, setInviteCode] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [heroIdx, setHeroIdx] = useState(0);
  const [sizeError, setSizeError] = useState('');
  const [selectedDemo, setSelectedDemo] = useState(null);
  const [loadingDemo, setLoadingDemo] = useState(null);
  const [demoError, setDemoError] = useState('');
  const inputRef = useRef(null);
  const demoRequest = useRef(null);

  const clearDemo = () => {
    demoRequest.current?.abort();
    demoRequest.current = null;
    setLoadingDemo(null);
    setSelectedDemo(null);
    setDemoError('');
  };

  const chooseFile = (f) => {
    if (!f || submitting) return;
    clearDemo();
    if (f.size > MAX_UPLOAD_BYTES || f.size === 0) {
      setFile(null);
      setSizeError(f.size ? `“${f.name}” is ${humanSize(f.size)}. Choose a file up to 10 MiB.` : 'Choose a file that contains audio.');
      if (inputRef.current) inputRef.current.value = '';
      return;
    }
    setSizeError('');
    setFile(f);
  };

  const loadDemo = async (clip) => {
    demoRequest.current?.abort();
    const request = new AbortController();
    demoRequest.current = request;
    setLoadingDemo(clip);
    setDemoError('');
    const timeout = setTimeout(() => request.abort('timeout'), 20000);
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}demo-clips/${clip.filename}`, {
        signal: request.signal,
        redirect: 'error',
      });
      if (!response.ok || response.headers.get('content-type')?.split(';')[0] !== 'video/mp4'
          || Number(response.headers.get('content-length')) > MAX_UPLOAD_BYTES) throw new Error();
      const blob = await response.blob();
      if (request.signal.aborted) return;
      if (!blob.size || blob.size > MAX_UPLOAD_BYTES) throw new Error();
      if (inputRef.current) inputRef.current.value = '';
      setFile(new File([blob], clip.filename, { type: 'video/mp4' }));
      setSizeError('');
      setSelectedDemo(clip);
    } catch {
      if (demoRequest.current === request && (!request.signal.aborted || request.signal.reason === 'timeout')) {
        setDemoError('Could not load the demo clip. Select it again to retry.');
      }
    } finally {
      clearTimeout(timeout);
      if (demoRequest.current === request) {
        demoRequest.current = null;
        setLoadingDemo(null);
      }
    }
  };

  useEffect(() => {
    const iv = setInterval(() => setHeroIdx((i) => i + 1), 2600);
    return () => {
      clearInterval(iv);
      const request = demoRequest.current;
      demoRequest.current = null;
      request?.abort();
    };
  }, []);

  const invited = mode === 'invited';
  const live = invited || mode === 'public';
  const showUploadNotice = live && file && !selectedDemo;
  const canAnalyse = Boolean(live && !submitting && !loadingDemo && file && (!invited || inviteCode.trim()));

  const submit = (event) => {
    event.preventDefault();
    if (!canAnalyse) return;
    onAnalyse({ file, inviteCode: invited ? inviteCode.trim() : undefined });
    setInviteCode('');
  };

  const tabStyle = (active) => ({
    background: 'none',
    border: 'none',
    padding: '0 0 6px',
    fontFamily: SANS,
    fontSize: 14,
    color: active ? CREAM : MUTE,
    borderBottom: active ? '1px solid #e8e5de' : '1px solid transparent',
    transition: 'color .2s',
  });

  return (
    <div>
      <section style={{ padding: '8vh var(--minutes-page-gutter, 44px) 90px', maxWidth: 1160, margin: '0 auto' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            marginBottom: 36,
          }}
        >
          <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: MUTE }}>
            New session
          </span>
          <div style={{ display: 'flex', gap: 26 }}>
            <button type="button" aria-pressed="true" data-hov="1" style={tabStyle(true)}>
              Upload file
            </button>
            <button type="button" disabled aria-label="YouTube URL (unavailable)" style={tabStyle(false)}>
              YouTube URL
            </button>
          </div>
        </div>

        <form onSubmit={submit}>
          <input
            ref={inputRef}
            type="file"
            aria-label="Audio or video file"
            accept={ACCEPT}
            style={{ display: 'none' }}
            onChange={(e) => chooseFile(e.target.files?.[0] || null)}
            disabled={submitting}
          />
          {!file ? (
            <button
              type="button"
              data-hov="1"
              disabled={submitting}
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                chooseFile(e.dataTransfer.files?.[0]);
              }}
              style={{
                display: 'block',
                width: '100%',
                color: 'inherit',
                border: `2px dashed rgba(232,229,222,${dragOver ? 0.85 : 0.45})`,
                borderRadius: 20,
                padding: '9vh 32px',
                textAlign: 'center',
                background: dragOver ? 'rgba(232,229,222,0.03)' : 'transparent',
                boxShadow: '8px 8px 0 rgba(232,229,222,0.10)',
                transition: 'all .25s cubic-bezier(.22,1,.36,1)',
              }}
            >
              <span
                style={{
                  display: 'block',
                  fontFamily: SANS,
                  fontWeight: 500,
                  fontSize: 'clamp(30px,4.4vw,58px)',
                  letterSpacing: '-0.02em',
                  marginBottom: 16,
                }}
              >
                Drop a recording here.
              </span>
              <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.05em', color: MUTE }}>
                MP3 · WAV · MP4 · MOV — up to 10 MiB and 120 seconds, or click to browse
              </span>
            </button>
          ) : (
            <div
              style={{
                border: '1.5px solid rgba(232,229,222,0.35)',
                background: 'rgba(232,229,222,0.03)',
                borderRadius: 18,
                boxShadow: '8px 8px 0 rgba(232,229,222,0.10)',
                padding: '44px 40px',
                display: 'flex',
                alignItems: 'baseline',
                justifyContent: 'space-between',
                gap: 24,
                flexWrap: 'wrap',
                animation: 'fadeUp .5s ease both',
              }}
            >
              <div>
                <div
                  style={{
                    fontFamily: SANS,
                    fontSize: 'clamp(22px,3vw,38px)',
                    letterSpacing: '-0.02em',
                    marginBottom: 10,
                    wordBreak: 'break-word',
                  }}
                >
                  {selectedDemo?.title ?? file.name}
                </div>
                <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.1em', color: MUTE }}>
                  {humanSize(file.size)} · {selectedDemo ? 'demo clip ready' : 'ready'}
                </div>
              </div>
              <button
                type="button"
                data-hov="1"
                disabled={submitting}
                onClick={() => {
                  clearDemo();
                  setFile(null);
                  inputRef.current.value = '';
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: MUTE,
                  fontFamily: MONO,
                  fontSize: 11,
                  letterSpacing: '0.06em',
                  padding: '6px 0',
                }}
              >
                Remove ×
              </button>
            </div>
          )}
          {sizeError && (
            <p
              role="alert"
              style={{
                margin: '14px 2px 0',
                fontFamily: MONO,
                fontSize: 11,
                lineHeight: 1.7,
                letterSpacing: '0.03em',
                color: '#d98c7a',
                maxWidth: 720,
              }}
            >
              ⚠ {sizeError}
            </p>
          )}

          <section className="minutes-demo-picker" aria-labelledby="minutes-demo-title">
            <h2 id="minutes-demo-title">Try a demo video</h2>
            <div className="minutes-demo-options">
              {DEMO_CLIPS.map((clip) => (
                <button type="button" key={clip.filename} data-hov="1"
                  aria-pressed={selectedDemo === clip} disabled={submitting || loadingDemo === clip}
                  onClick={() => loadDemo(clip)}>
                  {clip.title}
                </button>
              ))}
            </div>
            <p role="status" className="minutes-demo-status">
              {loadingDemo ? 'Loading demo clip…' : selectedDemo && !demoError ? 'Demo clip loaded.' : ''}
            </p>
            {demoError && <p role="alert" className="minutes-demo-status">{demoError}</p>}
          </section>

          {showUploadNotice && (
            <p id="demo-privacy" style={{ ...noteStyle, color: SUBTLE }}>
              Analyse sends audio to a third-party transcription provider. Use only synthetic or public, non-personal material.
            </p>
          )}
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 20,
              alignItems: 'stretch',
              marginTop: 20,
            }}
          >
            <div
              style={{
                display: 'flex',
                flex: '1 1 150px',
                alignItems: 'center',
                gap: 20,
                border: '1.5px solid rgba(232,229,222,0.30)',
                background: 'rgba(232,229,222,0.02)',
                borderRadius: 14,
                boxShadow: '6px 6px 0 rgba(232,229,222,0.10)',
                padding: '0 24px',
              }}
            >
              <label htmlFor="minutes-language" style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: MUTE }}>
                Language
              </label>
              <select
                id="minutes-language"
                data-hov="1"
                defaultValue="english"
                disabled={submitting}
                style={{
                  background: '#0e0e0d',
                  border: 'none',
                  color: CREAM,
                  fontFamily: MONO,
                  fontSize: 13,
                  letterSpacing: '0.06em',
                  padding: '20px 0',
                  appearance: 'none',
                  flex: 1,
                  minWidth: 0,
                }}
              >
                <option value="english">English</option>
                <option value="hinglish" disabled>Hinglish (unavailable)</option>
              </select>
            </div>
            <button
              data-hov="1"
              data-mag="1"
              type="submit"
              disabled={!canAnalyse}
              aria-describedby={showUploadNotice ? 'demo-privacy' : undefined}
              style={{
                background: canAnalyse ? CREAM : 'transparent',
                color: canAnalyse ? '#0e0e0d' : '#57544e',
                border: canAnalyse ? '1.5px solid #e8e5de' : '1.5px solid rgba(232,229,222,0.18)',
                boxShadow: canAnalyse ? '6px 6px 0 rgba(232,229,222,0.25)' : 'none',
                fontFamily: MONO,
                fontSize: 12,
                letterSpacing: '0.06em',
                padding: '0 44px',
                borderRadius: 14,
                minHeight: 62,
                transition:
                  'transform .3s cubic-bezier(.22,1,.36,1), background .25s, color .25s, box-shadow .25s',
              }}
            >
              {submitting ? 'Uploading…' : <>Analyse&nbsp;&nbsp;→</>}
            </button>
          </div>
          {invited && (
            <label style={{ ...noteStyle, display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
              Invite code
              <input type="password" autoComplete="off" value={inviteCode} disabled={submitting}
                onChange={(event) => setInviteCode(event.target.value)}
                style={{ background: 'transparent', color: CREAM, border: '1px solid #57544e', borderRadius: 8, padding: '8px 12px', maxWidth: '100%' }} />
            </label>
          )}
          {mode === 'loading' && <p role="status" style={noteStyle}>Checking live availability…</p>}
          {mode === 'sample' && <p role="status" style={noteStyle}>Live analysis is paused.</p>}
          {mode === 'unavailable' && (
            <p style={noteStyle}>
              <span role="status">Live analysis is unavailable. </span>
              <button type="button" onClick={onRetryAvailability} style={{ ...tabStyle(true), fontFamily: MONO, fontSize: 11 }}>
                Check availability
              </button>
            </p>
          )}
          {notice && <p role="status" style={noteStyle}>{notice}</p>}
          {uploadError && <p role="alert" style={{ ...noteStyle, color: '#d98c7a' }}>{uploadError}</p>}
        </form>
      </section>

      <div
        style={{
          borderTop: '1px solid rgba(232,229,222,0.10)',
          borderBottom: '1px solid rgba(232,229,222,0.10)',
          overflow: 'hidden',
          padding: '14px 0',
        }}
      >
        <div style={{ display: 'flex', width: 'max-content', animation: 'marqueeMove 26s linear infinite' }}>
          {[0, 1].map((k) => (
            <span
              key={k}
              style={{
                fontFamily: MONO,
                fontSize: 11,
                letterSpacing: '0.12em',
                color: MUTE,
                whiteSpace: 'nowrap',
                paddingRight: 60,
              }}
            >
              Transcribe — Summarise — Ask the meeting — Transcribe — Summarise — Ask the meeting —
            </span>
          ))}
        </div>
      </div>

      <section style={{ padding: '12vh var(--minutes-page-gutter, 44px) 10vh', display: 'flex', flexDirection: 'column' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 40,
            flexWrap: 'wrap',
          }}
        >
          <h1
            style={{
              margin: 0,
              fontFamily: SANS,
              fontWeight: 500,
              fontSize: 'var(--minutes-hero-size, clamp(64px,11.5vw,190px))',
              lineHeight: 0.94,
              letterSpacing: '-0.035em',
            }}
          >
            <span style={{ display: 'block', overflow: 'hidden', paddingBottom: '0.06em' }}>
              <span style={{ display: 'block', animation: 'lineUp 1.1s cubic-bezier(.22,1,.36,1) .15s both' }}>
                Every word,
              </span>
            </span>
            <span style={{ display: 'block', overflow: 'hidden', paddingBottom: '0.12em' }}>
              <span
                key={heroIdx}
                style={{
                  display: 'block',
                  fontWeight: 500,
                  color: SUBTLE,
                  animation: 'lineUp .8s cubic-bezier(.22,1,.36,1) both',
                }}
              >
                {HERO_WORDS[heroIdx % HERO_WORDS.length]}
              </span>
            </span>
          </h1>
          <div style={{ maxWidth: 300, paddingTop: '2.2vw', animation: 'fadeUp 1s ease .6s both' }}>
            <p style={{ margin: '0 0 14px', fontSize: 15, lineHeight: 1.7, color: SUBTLE }}>
              Upload a meeting. Minutes listens, writes the record, and answers for it — long after
              everyone hangs up.
            </p>
            <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: MUTE }}>
              No notes. No notetaker.
            </span>
          </div>
        </div>
        <div style={{ padding: '56px 0 0', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: MUTE }}>
            Every meeting, kept on record
          </span>
          <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: MUTE }}>
            EN
          </span>
        </div>
      </section>
    </div>
  );
}
