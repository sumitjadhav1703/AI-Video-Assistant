import { SANS, MONO, CREAM, DIM, STAGE_NAMES } from '../lib/theme';

const pad3 = (n) => String(Math.round(n)).padStart(3, '0');

const LINES = [
  'Listening closely.',
  'Writing it down.',
  'Naming the session.',
  'Finding what matters.',
  'Pulling the threads.',
  'Learning to answer.',
];

// Live pipeline view. `stageIdx` is driven by the backend's polled `step`
// (0..5 active, 6 = all done). The percentage is coarse — six real stages —
// so it advances per stage rather than pretending to be granular.
export default function Processing({ fileName, stageIdx }) {
  const idx = Math.max(0, stageIdx);
  const pct = Math.min(99, Math.max(3, Math.round(((idx + 0.5) / 6) * 100)));
  const line = LINES[Math.min(idx, LINES.length - 1)];

  const stages = STAGE_NAMES.map((name, i) => {
    const done = stageIdx > i;
    const active = stageIdx === i;
    return {
      idx: `0${i + 1}`,
      name,
      borderTop: i === 0 ? 'none' : '1px solid rgba(232,229,222,0.10)',
      color: done || active ? CREAM : DIM,
      status: done ? 'Done' : active ? 'In progress' : 'Waiting',
      statusColor: done ? '#6f6c65' : active ? CREAM : '#3a3833',
      anim: active ? 'pulseDot 1.4s ease infinite' : 'none',
    };
  });

  const bars = Array.from({ length: 42 }, (_, i) => ({
    width: 3,
    height: 110,
    background: CREAM,
    opacity: 0.85,
    borderRadius: 1,
    transformOrigin: 'bottom',
    animation: `wave ${(0.9 + (i % 5) * 0.14).toFixed(2)}s ease-in-out ${(i * 0.055).toFixed(3)}s infinite`,
  }));

  return (
    <section
      style={{
        minHeight: 'calc(100vh - 180px)',
        display: 'flex',
        flexDirection: 'column',
        padding: '8vh 44px 44px',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          fontFamily: MONO,
          fontSize: 11,
          letterSpacing: '0.08em',
          color: '#6f6c65',
          marginBottom: 26,
          animation: 'fadeIn .6s ease both',
          wordBreak: 'break-word',
        }}
      >
        Processing — {fileName}
      </div>
      <h1
        style={{
          margin: '0 0 7vh',
          fontFamily: SANS,
          fontWeight: 300,
          fontSize: 'clamp(44px,7vw,110px)',
          letterSpacing: '-0.03em',
          lineHeight: 1,
        }}
      >
        <span style={{ display: 'block', overflow: 'hidden', paddingBottom: '0.1em' }}>
          <span key={line} style={{ display: 'block', animation: 'lineUp .9s cubic-bezier(.22,1,.36,1) both' }}>
            {line}
          </span>
        </span>
      </h1>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 120, maxWidth: 720 }}>
        {bars.map((s, i) => (
          <div key={i} style={s} />
        ))}
      </div>
      <div
        style={{
          marginTop: '7vh',
          maxWidth: 520,
          border: '1.5px solid rgba(232,229,222,0.32)',
          background: 'rgba(232,229,222,0.025)',
          borderRadius: 16,
          boxShadow: '8px 8px 0 rgba(232,229,222,0.10)',
          padding: '6px 28px',
        }}
      >
        {stages.map((st) => (
          <div
            key={st.idx}
            style={{
              display: 'grid',
              gridTemplateColumns: '44px 1fr auto',
              alignItems: 'baseline',
              padding: '16px 0',
              borderTop: st.borderTop,
            }}
          >
            <span style={{ fontFamily: MONO, fontSize: 10, color: DIM }}>{st.idx}</span>
            <span style={{ fontSize: 14, color: st.color, transition: 'color .4s' }}>{st.name}</span>
            <span
              style={{
                fontFamily: MONO,
                fontSize: 10,
                letterSpacing: '0.05em',
                color: st.statusColor,
                animation: st.anim,
              }}
            >
              {st.status}
            </span>
          </div>
        ))}
      </div>
      <div
        style={{
          position: 'absolute',
          right: 24,
          bottom: '-2vw',
          fontFamily: SANS,
          fontWeight: 300,
          fontSize: 'clamp(140px,24vw,360px)',
          lineHeight: 0.8,
          letterSpacing: '-0.05em',
          color: 'rgba(232,229,222,0.07)',
          fontVariantNumeric: 'tabular-nums',
          pointerEvents: 'none',
        }}
      >
        {pad3(pct)}
      </div>
    </section>
  );
}
