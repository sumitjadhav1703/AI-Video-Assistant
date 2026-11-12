import { useEffect, useRef, useState } from 'react';
import { SANS, MONO, CREAM, SUBTLE, MUTE } from '../lib/theme';
import { humanSize } from '../lib/parse';

const ACCEPT = '.mp3,.wav,.m4a,.mp4,.mov,.mkv,.webm,.aac,.ogg,.flac';
const HERO_WORDS = ['remembered.', 'recorded.', 'summarised.', 'answered.', 'searchable.'];
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const ANALYSED_SECONDS = 600;
const DEMO_CLIPS = [
  { title: 'Large language models explained', filename: 'llm-explained.mp3' },
  { title: 'Generative AI explained', filename: 'generative-ai-explained.mp3' },
  { title: 'How AI images and videos work', filename: 'ai-images-videos.mp3' },
];
// Resolves to duration in seconds, or null if it cannot be read (errors/timeouts are silent).
const readDuration = (file) => new Promise((resolve) => {
  const url = URL.createObjectURL(file);
  const media = document.createElement(file.type.startsWith('video/') ? 'video' : 'audio');
  const done = (value) => {
    clearTimeout(timer);
    media.removeAttribute('src');
    media.load();
    URL.revokeObjectURL(url);
    resolve(value);
  };
  const timer = setTimeout(() => done(null), 8000);
  media.preload = 'metadata';
  media.onloadedmetadata = () => done(Number.isFinite(media.duration) ? media.duration : null);
  media.onerror = () => done(null);
  media.src = url;
});
const youtubeHintStyle = {
  position: 'absolute', top: 'calc(100% + 10px)', right: 0, zIndex: 5, width: 'min(320px, 80vw)',
  padding: '12px 14px', borderRadius: 12, border: '1px solid rgba(232,229,222,0.25)', background: '#1c1b19',
  color: CREAM, fontFamily: SANS, fontSize: 13, lineHeight: 1.55, textAlign: 'left', boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
};
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
  const [durationSec, setDurationSec] = useState(null);
  const [youtubeHint, setYoutubeHint] = useState(false);
  const inputRef = useRef(null);
  const demoRequest = useRef(null);

  useEffect(() => {
    setDurationSec(null);
    if (!file) return undefined;
    let stale = false;
    readDuration(file).then((d) => { if (!stale) setDurationSec(d); }, () => {});
    return () => { stale = true; };
  }, [file]);

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
      setSizeError(f.size ? `“${f.name}” is ${humanSize(f.size)}. Choose a file up to 25 MiB.` : 'Choose a file that contains audio.');
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
      if (!response.ok || response.headers.get('content-type')?.split(';')[0] !== 'audio/mpeg'
          || Number(response.headers.get('content-length')) > MAX_UPLOAD_BYTES) throw new Error();
      const blob = await response.blob();
      if (request.signal.aborted) return;
      if (!blob.size || blob.size > MAX_UPLOAD_BYTES) throw new Error();
      if (inputRef.current) inputRef.current.value = '';
      setFile(new File([blob], clip.filename, { type: 'audio/mpeg' }));
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
            <span
              style={{ position: 'relative', display: 'inline-block' }}
              onMouseEnter={() => setYoutubeHint(true)}
              onMouseLeave={() => setYoutubeHint(false)}
            >
              {/* aria-disabled, not disabled: disabled buttons get no hover, focus or click to explain themselves. */}
              <button
                type="button"
                aria-disabled="true"
                aria-label="YouTube URL (unavailable)"
                aria-describedby="youtube-unavailable"
                onClick={() => setYoutubeHint((shown) => !shown)}
                onFocus={() => setYoutubeHint(true)}
                onBlur={() => setYoutubeHint(false)}
                style={{ ...tabStyle(false), cursor: 'not-allowed' }}
              >
                YouTube URL
              </button>
              <span id="youtube-unavailable" role="tooltip" hidden={!youtubeHint} style={youtubeHintStyle}>
                YouTube links aren&rsquo;t supported here: YouTube blocks downloads from hosted servers.
                Download the video and upload the file instead. Running locally? The command-line tool
                (<code>python -m backend.cli</code>) accepts YouTube links when <code>ENABLE_YOUTUBE=true</code>.
              </span>
            </span>
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
                MP3 · WAV · MP4 · MOV — up to 25 MiB; the first 10 minutes are analysed
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

          {file && durationSec > ANALYSED_SECONDS && (
            <p role="status" style={noteStyle}>
              This recording is {Math.round(durationSec / 60)} min. Only the first {ANALYSED_SECONDS / 60} minutes will be analysed.
            </p>
          )}
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
