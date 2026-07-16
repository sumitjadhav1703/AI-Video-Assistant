import { useState } from 'react';
import { SANS, MONO, CREAM, SUBTLE, MUTE, DIM } from '../lib/theme';
import { toItems, toLines, toParagraphs, stripMd, humanSize } from '../lib/parse';
import Chat from './Chat';

const CARD = {
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
};
const LABEL = { fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: MUTE };

const TODAY = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });

export default function Results({ result, meta, chat, onAsk }) {
  const [transcriptOpen, setTranscriptOpen] = useState(false);

  // The backend emits a "No … found." placeholder string when the LLM extracts
  // nothing. Detect it so we render a clean empty state instead of a fake "01"
  // list item that reads as broken.
  const EMPTY_RE = /^no\b.*\bfound\.?$/i;
  const buildGroup = (label, raw, emptyNote) => {
    const items = toItems(raw);
    const empty = items.length === 0 || (items.length === 1 && EMPTY_RE.test(items[0]));
    return { label, items: empty ? [] : items, empty, emptyNote };
  };

  const groups = [
    buildGroup('Action items', result.action_items, 'Nothing to action from this one.'),
    buildGroup('Key decisions', result.key_decisions, 'No decisions were made on the record.'),
    buildGroup('Open questions', result.open_questions, 'Nothing was left open.'),
  ];

  const metaBits = [
    meta.fileName,
    meta.fileSize != null ? humanSize(meta.fileSize) : null,
    meta.language === 'hinglish' ? 'Hinglish' : 'English',
  ].filter(Boolean);

  return (
    <article>
      <section style={{ padding: '9vh 44px 60px', maxWidth: 1160, margin: '0 auto', position: 'relative' }}>
        <div style={{ ...LABEL, marginBottom: 30, animation: 'fadeIn .6s ease both' }}>Session — {TODAY}</div>
        <h1
          style={{
            margin: '0 0 34px',
            fontFamily: SANS,
            fontWeight: 500,
            fontSize: 'clamp(44px,6.6vw,104px)',
            lineHeight: 1.0,
            letterSpacing: '-0.03em',
            textWrap: 'balance',
            maxWidth: '16ch',
          }}
        >
          <span style={{ display: 'block', overflow: 'hidden', paddingBottom: '0.05em' }}>
            <span style={{ display: 'block', animation: 'lineUp 1s cubic-bezier(.22,1,.36,1) .1s both' }}>
              {stripMd(result.title) || 'Session record'}
            </span>
          </span>
        </h1>
        <div
          style={{
            display: 'flex',
            gap: 22,
            flexWrap: 'wrap',
            ...LABEL,
            animation: 'fadeIn .8s ease .5s both',
          }}
        >
          {metaBits.map((b, i) => (
            <span key={i} style={{ wordBreak: 'break-word' }}>
              {b}
            </span>
          ))}
        </div>
      </section>

      {/* Summary */}
      <section style={{ borderTop: '1px solid rgba(232,229,222,0.10)', padding: '56px 44px 14px' }}>
        <div style={{ ...CARD, animation: 'fadeUp .9s cubic-bezier(.22,1,.36,1) .15s both' }}>
          <span style={LABEL}>Summary</span>
          <div style={{ maxWidth: 760 }}>
            {toLines(result.summary).map((p, i) => (
              <p
                key={i}
                style={{
                  margin: i === 0 ? '0 0 20px' : '0 0 16px',
                  fontSize: i === 0 ? 'clamp(19px,1.9vw,24px)' : 15,
                  lineHeight: i === 0 ? 1.5 : 1.75,
                  color: i === 0 ? CREAM : SUBTLE,
                  letterSpacing: i === 0 ? '-0.005em' : 0,
                }}
              >
                {p}
              </p>
            ))}
          </div>
        </div>
      </section>

      {/* Findings */}
      {groups.map((g, gi) => (
        <section key={g.label} style={{ padding: '14px 44px' }}>
          <div style={{ ...CARD, animation: 'fadeUp .9s cubic-bezier(.22,1,.36,1) .25s both' }}>
            <div>
              <div
                style={{
                  fontFamily: SANS,
                  fontWeight: 300,
                  fontSize: 'clamp(60px,7vw,110px)',
                  lineHeight: 0.9,
                  letterSpacing: '-0.04em',
                  color: 'rgba(232,229,222,0.10)',
                  marginBottom: 14,
                }}
              >
                0{gi + 1}
              </div>
              <span style={LABEL}>{g.label}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', maxWidth: 760 }}>
              {g.empty && (
                <div style={{ padding: '20px 0' }}>
                  <span
                    style={{
                      fontFamily: SANS,
                      fontSize: 'clamp(16px,1.5vw,19px)',
                      lineHeight: 1.4,
                      letterSpacing: '-0.005em',
                      color: MUTE,
                    }}
                  >
                    {g.emptyNote}
                  </span>
                </div>
              )}
              {g.items.map((text, i) => (
                <div
                  key={i}
                  data-hov="1"
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '36px 1fr',
                    alignItems: 'baseline',
                    padding: '20px 0',
                    borderBottom: '1px solid rgba(232,229,222,0.07)',
                    transition: 'transform .3s cubic-bezier(.22,1,.36,1)',
                  }}
                >
                  <span style={{ fontFamily: MONO, fontSize: 10, color: DIM }}>0{i + 1}</span>
                  <span
                    style={{
                      fontFamily: SANS,
                      fontSize: 'clamp(17px,1.9vw,24px)',
                      lineHeight: 1.4,
                      letterSpacing: '-0.005em',
                      color: '#dedbd3',
                    }}
                  >
                    {text}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>
      ))}

      {/* Transcript */}
      <section style={{ padding: '14px 44px' }}>
        <div style={{ ...CARD, animation: 'fadeUp .9s cubic-bezier(.22,1,.36,1) .3s both' }}>
          <span style={LABEL}>Transcript</span>
          <div style={{ maxWidth: 760 }}>
            <button
              data-hov="1"
              onClick={() => setTranscriptOpen((o) => !o)}
              style={{
                background: 'none',
                border: '1.5px solid rgba(232,229,222,0.45)',
                color: SUBTLE,
                fontFamily: MONO,
                fontSize: 11,
                letterSpacing: '0.06em',
                padding: '14px 24px',
                borderRadius: 999,
                boxShadow: '4px 4px 0 rgba(232,229,222,0.14)',
                transition: 'all .22s cubic-bezier(.22,1,.36,1)',
              }}
            >
              {transcriptOpen ? 'Hide full transcript −' : 'Show full transcript +'}
            </button>
            {transcriptOpen && (
              <div style={{ marginTop: 34, animation: 'fadeUp .5s ease both' }}>
                {toParagraphs(result.transcript).length ? (
                  toParagraphs(result.transcript).map((p, i) => (
                    <p key={i} style={{ margin: '0 0 18px', fontSize: 14, lineHeight: 1.8, color: SUBTLE }}>
                      {p}
                    </p>
                  ))
                ) : (
                  <p style={{ margin: 0, fontSize: 14, lineHeight: 1.8, color: MUTE }}>
                    No transcript text was returned.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      <Chat chat={chat} onAsk={onAsk} />
    </article>
  );
}
