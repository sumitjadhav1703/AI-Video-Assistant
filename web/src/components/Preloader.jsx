import { useEffect, useState } from 'react';
import { SANS, MONO, INK, CREAM, MUTE } from '../lib/theme';

const pad3 = (n) => String(Math.round(n)).padStart(3, '0');

// Brief boot intro: counts 0 -> 100 over ~1s, then calls onDone.
export default function Preloader({ onDone }) {
  const [pct, setPct] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setPct((p) => {
        const next = Math.min(100, p + 2);
        if (next >= 100) {
          clearInterval(id);
          setTimeout(onDone, 450);
        }
        return next;
      });
    }, 20);
    return () => clearInterval(id);
  }, [onDone]);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: INK,
        zIndex: 9500,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '36px 44px',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: MONO,
          fontSize: 11,
          letterSpacing: '0.08em',
          color: MUTE,
        }}
      >
        <span>Minutes</span>
        <span>Meeting intelligence — ©2026</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 24 }}>
        <div
          style={{
            fontFamily: SANS,
            fontWeight: 300,
            fontSize: 'clamp(120px,24vw,340px)',
            lineHeight: 0.8,
            letterSpacing: '-0.04em',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {pad3(pct)}
        </div>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 18,
            paddingBottom: 12,
          }}
        >
          <span
            style={{
              fontFamily: MONO,
              fontSize: 11,
              letterSpacing: '0.08em',
              color: MUTE,
              animation: 'pulseDot 1.4s ease infinite',
            }}
          >
            Preparing the record
          </span>
          <div style={{ width: 'min(280px,30vw)', height: 1, background: 'rgba(232,229,222,0.14)' }}>
            <div style={{ height: 1, background: CREAM, width: `${pct}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}
