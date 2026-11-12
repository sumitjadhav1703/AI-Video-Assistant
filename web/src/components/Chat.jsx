import { useRef, useState } from 'react';
import { SANS, MONO, CREAM, SUBTLE, MUTE } from '../lib/theme';

function formatTime(ms) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

function sourceLink(source, start) {
  if (start == null) return null;
  try {
    const url = new URL(source);
    if (url.protocol !== 'https:' || !['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'].includes(url.hostname)) return null;
    url.searchParams.set('t', String(Math.floor(start / 1000)));
    return url.href;
  } catch { return null; }
}

export default function Chat({ chat, onAsk, source, economyOnly, presetQuestions, onSeek }) {
  const [tier, setTier] = useState('economy');
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);

  const send = async () => {
    const q = draft.trim();
    if (!q || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setDraft('');
    try {
      await onAsk(q, economyOnly ? 'economy' : tier);
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  };

  return (
    <section className="results-chat" aria-label={presetQuestions ? 'Try a sample question' : 'Ask the meeting'}>
      <div
        style={{
          animation: 'fadeUp .9s cubic-bezier(.22,1,.36,1) .35s both',
          maxWidth: 1160,
          margin: '0 auto',
          display: 'grid',
          gridTemplateColumns: 'var(--result-card-columns, minmax(140px,220px) 1fr)',
          gap: 'var(--result-card-gap, 32px)',
          border: '1.5px solid rgba(232,229,222,0.32)',
          background: 'rgba(232,229,222,0.025)',
          borderRadius: 18,
          padding: 'var(--result-card-padding, 44px 48px)',
          boxShadow: '8px 8px 0 rgba(232,229,222,0.10)',
        }}
      >
        <h2 className="results-chat-heading">
          {presetQuestions ? 'Try a sample question' : 'Ask the meeting'}
        </h2>
        <div style={{ maxWidth: 760 }}>
          {presetQuestions && (
            <div className="demo-sample-questions">
              {presetQuestions.map((question) => (
                <button
                  type="button"
                  key={question}
                  className="demo-sample-control"
                  aria-pressed={chat[0]?.q === question}
                  onClick={() => onAsk(question)}
                >
                  {question}
                </button>
              ))}
            </div>
          )}
          {!presetQuestions && chat.length === 0 && (
            <p
              style={{
                margin: '0 0 var(--chat-intro-gap, 34px)',
                fontFamily: SANS,
                fontWeight: 500,
                fontSize: 'var(--chat-intro-size, clamp(22px,2.4vw,30px))',
                color: SUBTLE,
                letterSpacing: '-0.01em',
              }}
            >
              Ask what was decided, who said what, or what’s still open.
            </p>
          )}

          <div className="chat-thread" aria-live="polite" aria-relevant="additions text">
            {chat.map((msg) => (
              <div key={msg.id} style={{ animation: 'fadeUp .45s ease both' }}>
                {!presetQuestions && (
                  <p
                    style={{
                      margin: '0 0 var(--chat-question-gap, 16px)',
                      fontFamily: SANS,
                      fontWeight: 500,
                      fontSize: 'var(--chat-question-size, clamp(22px,2.4vw,30px))',
                      lineHeight: 1.3,
                      letterSpacing: '-0.01em',
                    }}
                  >
                    {msg.q}
                  </p>
                )}
                <div style={{ borderLeft: '1px solid rgba(232,229,222,0.25)', paddingLeft: 'var(--chat-answer-gutter, 24px)' }}>
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
                  {!msg.pending && msg.citations?.length > 0 && (
                    <div style={{ marginTop: 16, color: SUBTLE, fontSize: 13 }}>
                      <strong>Sources</strong>
                      {msg.citations.map((citation, index) => {
                        const timed = citation.timing_precision !== 'unknown' && citation.start_ms != null;
                        const href = timed ? sourceLink(source, citation.start_ms) : null;
                        let sourceControl = <span>{citation.chunk_id}</span>;
                        if (timed && onSeek) {
                          sourceControl = (
                            <button type="button" className="demo-sample-control" onClick={() => onSeek(citation.start_ms)}>
                              Jump to {formatTime(citation.start_ms)}
                            </button>
                          );
                        } else if (href) {
                          sourceControl = <a href={href} target="_blank" rel="noreferrer" style={{ color: CREAM }}>Open source at {formatTime(citation.start_ms)}</a>;
                        }
                        return (
                          <p key={`${citation.chunk_id}-${index}`} style={{ lineHeight: 1.6 }}>
                            {sourceControl}
                            {' · '}{!timed || citation.end_ms == null
                              ? 'Time unavailable'
                              : `${citation.timing_precision === 'piece' ? 'Approx. ' : ''}${formatTime(citation.start_ms)}–${formatTime(citation.end_ms)}`}
                            {' · '}{citation.text}
                          </p>
                        );
                      })}
                    </div>
                  )}
                  {!msg.pending && msg.model?.tier && <p style={{ color: MUTE, fontSize: 12 }}>Model tier: {msg.model.tier}</p>}
                </div>
              </div>
            ))}
          </div>

          {!presetQuestions && <>
            {!economyOnly && <label style={{ display: 'block', color: SUBTLE, marginBottom: 12 }}>Model tier{' '}
              <select value={tier} onChange={(e) => setTier(e.target.value)} disabled={sending} style={{ background: '#0e0e0d', color: CREAM, padding: 8 }}>
                <option value="economy">Economy</option><option value="strong">Strong</option>
              </select>
            </label>}
            <div className="chat-compose" style={{ borderTop: '1px solid rgba(232,229,222,0.10)', paddingTop: 'var(--chat-compose-gutter, 28px)' }}>
              <input
                data-hov="1"
                value={draft}
                maxLength={1000}
                disabled={sending}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') send();
                }}
                aria-label="Question about this meeting"
                placeholder="Ask about this meeting"
                style={{
                  flex: 1,
                  minWidth: 0,
                  background: 'none',
                  border: '1px solid rgba(232,229,222,0.18)',
                  color: CREAM,
                  fontSize: 15,
                  fontFamily: SANS,
                  padding: 'var(--chat-input-padding, 18px 22px)',
                  minHeight: 44,
                  borderRadius: 14,
                  boxShadow: '4px 4px 0 rgba(232,229,222,0.08)',
                  transition: 'border-color .2s, background .2s',
                }}
              />
              <button
                data-hov="1"
                data-mag="1"
                onClick={send}
                disabled={sending || !draft.trim()}
                style={{
                  background: CREAM,
                  color: '#0e0e0d',
                  border: '1.5px solid #e8e5de',
                  fontFamily: MONO,
                  fontSize: 11,
                  letterSpacing: '0.06em',
                  padding: '0 var(--chat-button-padding, 32px)',
                  borderRadius: 14,
                  boxShadow: '5px 5px 0 rgba(232,229,222,0.25)',
                  transition: 'transform .3s cubic-bezier(.22,1,.36,1), background .2s, box-shadow .2s',
                }}
              >
                Ask
              </button>
            </div>
          </>}
        </div>
      </div>
    </section>
  );
}
