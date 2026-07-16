import { useState } from 'react';
import { SANS, MONO, CREAM, SUBTLE, MUTE } from '../lib/theme';

// "Ask the meeting" — real RAG chat. Each message is answered by the backend,
// scoped to this job. `chat` items: { id, q, a, pending }.
export default function Chat({ chat, onAsk }) {
  const [draft, setDraft] = useState('');

  const send = () => {
    const q = draft.trim();
    if (!q) return;
    onAsk(q);
    setDraft('');
  };

  return (
    <section style={{ padding: '14px 44px 100px' }}>
      <div
        style={{
          animation: 'fadeUp .9s cubic-bezier(.22,1,.36,1) .35s both',
          maxWidth: 1160,
          margin: '0 auto',
          display: 'grid',
          gridTemplateColumns: 'minmax(140px,220px) 1fr',
          gap: 32,
          border: '1.5px solid rgba(232,229,222,0.32)',
          background: 'rgba(232,229,222,0.025)',
          borderRadius: 18,
          padding: '44px 48px',
          boxShadow: '8px 8px 0 rgba(232,229,222,0.10)',
        }}
      >
        <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: MUTE }}>
          Ask the meeting
        </span>
        <div style={{ maxWidth: 760 }}>
          {chat.length === 0 && (
            <p
              style={{
                margin: '0 0 34px',
                fontFamily: SANS,
                fontWeight: 500,
                fontSize: 'clamp(22px,2.4vw,30px)',
                color: MUTE,
                letterSpacing: '-0.01em',
              }}
            >
              Ask what was decided, who said what, or what’s still open.
            </p>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 38, marginBottom: 38 }}>
            {chat.map((msg) => (
              <div key={msg.id} style={{ animation: 'fadeUp .45s ease both' }}>
                <p
                  style={{
                    margin: '0 0 16px',
                    fontFamily: SANS,
                    fontWeight: 500,
                    fontSize: 'clamp(22px,2.4vw,30px)',
                    lineHeight: 1.3,
                    letterSpacing: '-0.01em',
                  }}
                >
                  {msg.q}
                </p>
                <div style={{ borderLeft: '1px solid rgba(232,229,222,0.25)', paddingLeft: 24 }}>
                  {msg.pending ? (
                    <span
                      style={{
                        fontFamily: MONO,
                        fontSize: 11,
                        letterSpacing: '0.05em',
                        color: MUTE,
                        animation: 'pulseDot 1.2s ease infinite',
                      }}
                    >
                      Reading the transcript…
                    </span>
                  ) : (
                    <p style={{ margin: 0, fontSize: 15, lineHeight: 1.75, color: SUBTLE, whiteSpace: 'pre-wrap' }}>
                      {msg.a}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 14, borderTop: '1px solid rgba(232,229,222,0.10)', paddingTop: 28 }}>
            <input
              data-hov="1"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') send();
              }}
              placeholder="What were the main decisions made?"
              style={{
                flex: 1,
                background: 'none',
                border: '1px solid rgba(232,229,222,0.18)',
                color: CREAM,
                fontSize: 15,
                fontFamily: SANS,
                padding: '18px 22px',
                borderRadius: 14,
                boxShadow: '4px 4px 0 rgba(232,229,222,0.08)',
                transition: 'border-color .2s, background .2s',
              }}
            />
            <button
              data-hov="1"
              data-mag="1"
              onClick={send}
              style={{
                background: CREAM,
                color: '#0e0e0d',
                border: '1.5px solid #e8e5de',
                fontFamily: MONO,
                fontSize: 11,
                letterSpacing: '0.06em',
                padding: '0 32px',
                borderRadius: 14,
                boxShadow: '5px 5px 0 rgba(232,229,222,0.25)',
                transition: 'transform .3s cubic-bezier(.22,1,.36,1), background .2s, box-shadow .2s',
              }}
            >
              Ask
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
