import { useEffect, useRef, useState } from 'react';
import { SANS, MONO, CREAM, SUBTLE, MUTE } from '../lib/theme';
import { humanSize } from '../lib/parse';

const ACCEPT = '.mp3,.wav,.m4a,.mp4,.mov,.mkv,.webm,.aac,.ogg,.flac';
const HERO_WORDS = ['remembered.', 'recorded.', 'summarised.', 'answered.', 'searchable.'];

// New-session screen: source tabs, file drop / YouTube URL, language, Analyse.
export default function Empty({ onAnalyse }) {
  const [source, setSource] = useState('upload'); // 'upload' | 'yt'
  const [file, setFile] = useState(null);
  const [ytUrl, setYtUrl] = useState('');
  const [lang, setLang] = useState('english');
  const [dragOver, setDragOver] = useState(false);
  const [heroIdx, setHeroIdx] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    const iv = setInterval(() => setHeroIdx((i) => i + 1), 2600);
    return () => clearInterval(iv);
  }, []);

  const canAnalyse = source === 'upload' ? !!file : ytUrl.trim().length > 8;

  const submit = () => {
    if (!canAnalyse) return;
    if (source === 'upload') onAnalyse({ file, language: lang });
    else onAnalyse({ youtubeUrl: ytUrl.trim(), language: lang });
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
      <section style={{ padding: '8vh 44px 90px', maxWidth: 1160, margin: '0 auto' }}>
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
            <button data-hov="1" onClick={() => setSource('upload')} style={tabStyle(source === 'upload')}>
              Upload file
            </button>
            <button data-hov="1" onClick={() => setSource('yt')} style={tabStyle(source === 'yt')}>
              YouTube URL
            </button>
          </div>
        </div>

        {source === 'upload' && (
          <>
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              style={{ display: 'none' }}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            {!file ? (
              <div
                data-hov="1"
                onClick={() => inputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  const f = e.dataTransfer.files?.[0];
                  if (f) setFile(f);
                }}
                style={{
                  border: `2px dashed rgba(232,229,222,${dragOver ? 0.85 : 0.45})`,
                  borderRadius: 20,
                  padding: '9vh 32px',
                  textAlign: 'center',
                  background: dragOver ? 'rgba(232,229,222,0.03)' : 'transparent',
                  boxShadow: '8px 8px 0 rgba(232,229,222,0.10)',
                  transition: 'all .25s cubic-bezier(.22,1,.36,1)',
                }}
              >
                <div
                  style={{
                    fontFamily: SANS,
                    fontWeight: 500,
                    fontSize: 'clamp(30px,4.4vw,58px)',
                    letterSpacing: '-0.02em',
                    marginBottom: 16,
                  }}
                >
                  Drop a recording here.
                </div>
                <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.05em', color: MUTE }}>
                  MP3 · WAV · MP4 · MOV — up to 200 MB, or click to browse
                </div>
              </div>
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
                    {file.name}
                  </div>
                  <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.1em', color: MUTE }}>
                    {humanSize(file.size)} · ready
                  </div>
                </div>
                <button
                  data-hov="1"
                  onClick={() => setFile(null)}
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
          </>
        )}

        {source === 'yt' && (
          <div>
            <input
              data-hov="1"
              value={ytUrl}
              onChange={(e) => setYtUrl(e.target.value)}
              placeholder="https://youtube.com/watch?v=…"
              style={{
                width: '100%',
                background: 'none',
                border: '1.5px solid rgba(232,229,222,0.30)',
                color: CREAM,
                fontFamily: MONO,
                fontSize: 14,
                padding: '28px',
                borderRadius: 16,
                boxShadow: '6px 6px 0 rgba(232,229,222,0.08)',
                transition: 'border-color .2s, background .2s',
              }}
            />
            <p
              style={{
                margin: '14px 2px 0',
                fontFamily: MONO,
                fontSize: 11,
                lineHeight: 1.7,
                letterSpacing: '0.03em',
                color: MUTE,
                maxWidth: 720,
              }}
            >
              ⚠ Blocked on the hosted demo. YouTube rejects downloads from cloud/datacenter IP
              ranges with a “Sign in to confirm you’re not a bot” check, so this path fails on the
              deployed backend. It works normally when you run the project on your own machine
              (a residential IP). On the demo, use Upload file instead.
            </p>
          </div>
        )}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr auto',
            gap: 20,
            alignItems: 'stretch',
            marginTop: 20,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 20,
              border: '1.5px solid rgba(232,229,222,0.30)',
              background: 'rgba(232,229,222,0.02)',
              borderRadius: 14,
              boxShadow: '6px 6px 0 rgba(232,229,222,0.10)',
              padding: '0 24px',
            }}
          >
            <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: MUTE }}>
              Language
            </span>
            <select
              data-hov="1"
              value={lang}
              onChange={(e) => setLang(e.target.value)}
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
              }}
            >
              <option value="english">English</option>
              <option value="hinglish">Hinglish</option>
            </select>
          </div>
          <button
            data-hov="1"
            data-mag="1"
            onClick={submit}
            disabled={!canAnalyse}
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
            Analyse&nbsp;&nbsp;→
          </button>
        </div>
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
              Transcribe — Summarise — Ask the meeting — Released on close — Transcribe — Summarise —
              Ask the meeting — Released on close —
            </span>
          ))}
        </div>
      </div>

      <section style={{ padding: '12vh 44px 10vh', display: 'flex', flexDirection: 'column' }}>
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
              fontSize: 'clamp(64px,11.5vw,190px)',
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
            EN · HINGLISH
          </span>
        </div>
      </section>
    </div>
  );
}
