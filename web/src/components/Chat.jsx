import { useRef, useState } from 'react';
import { SANS, MONO, CREAM, SUBTLE, MUTE } from '../lib/theme';

function formatTime(ms) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export default function Chat({ chat, onAsk, presetQuestions, onSeek }) {
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);

  // The backend rejects questions over 2048 UTF-8 bytes; maxLength counts UTF-16 units.
  const tooLong = new TextEncoder().encode(draft.trim()).length > 2048;

  const send = async () => {
    const q = draft.trim();
    if (!q || tooLong || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setDraft('');
    try {
      await onAsk(q);
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
            {chat.map((msg) => {
              const abstained = !msg.pending && msg.abstained === true;
              return (
              <div key={msg.id} className="chat-turn">
                {!presetQuestions && (
                  <div className="chat-q">
                    <span className="chat-q-label">You asked</span>
                    <p className="chat-q-text">{msg.q}</p>
                  </div>
                )}
                <div className={`chat-a${abstained ? ' chat-a-abstained' : ''}${msg.error ? ' chat-a-error' : ''}`}>
                  {msg.pending ? (
                    <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.05em', color: MUTE, animation: 'pulseDot 1.2s ease infinite' }}>
                      Reading the transcript…
                    </span>
                  ) : (
                    <>
                      <p className="chat-a-text" role={msg.error ? 'alert' : undefined}>{msg.a}</p>
                      {abstained && <p className="chat-a-hint">Try rephrasing or ask about something mentioned in the recording.</p>}
                    </>
                  )}
                  {!msg.pending && msg.citations?.length > 0 && (
                    <div className="chat-sources">
                      <strong className="chat-sources-label">Sources</strong>
                      {msg.citations.map((citation, index) => {
                        const timed = citation.timing_precision !== 'unknown' && citation.start_ms != null;
                        const range = timed
                          ? `${citation.timing_precision === 'piece' ? '~' : ''}${formatTime(citation.start_ms)}${citation.end_ms == null ? '' : `–${formatTime(citation.end_ms)}`}`
                          : null;
                        let chip = range && <span className="chat-chip">{range}</span>;
                        if (timed && onSeek) {
                          chip = <button type="button" className="chat-chip" aria-label={`Jump to ${range}`} onClick={() => onSeek(citation.start_ms)}>{range}</button>;
                        }
                        return (
                          <div key={`${citation.chunk_id}-${index}`} className="chat-cite">
                            {chip}
                            <q className="chat-cite-text">{citation.text}</q>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
              );
            })}
          </div>

          {!presetQuestions && <>
            <div className="chat-compose" style={{ borderTop: '1px solid rgba(232,229,222,0.10)', paddingTop: 'var(--chat-compose-gutter, 28px)' }}>
              <input
                data-hov="1"
                value={draft}
                maxLength={1000}
                disabled={sending}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  // Enter while an IME is composing confirms the candidate, not the question.
                  if (e.key === 'Enter' && !e.nativeEvent.isComposing && e.keyCode !== 229) send();
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
                disabled={sending || !draft.trim() || tooLong}
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
            {tooLong && <p role="status" className="chat-a-hint">This question is too long. Shorten it to ask.</p>}
          </>}
        </div>
      </div>
    </section>
  );
}
