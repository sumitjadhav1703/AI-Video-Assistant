import { useEffect, useRef, useState } from 'react';
import { SANS, MONO, CREAM, MUTE, DIM } from '../lib/theme';

// Top navigation: logo, live status, clock, and (when a session is active) a
// "New session" reset. Nav + veil hide on scroll-down and return on scroll-up.
export default function Nav({ status, dotActive, dotPulse, showReset, onReset }) {
  const navRef = useRef(null);
  const veilRef = useRef(null);
  const [clock, setClock] = useState('');

  useEffect(() => {
    const tick = () =>
      setClock(
        `${new Date().toLocaleTimeString('en-GB', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })} local`,
      );
    tick();
    const iv = setInterval(tick, 1000);

    let lastY = window.scrollY;
    const onScroll = () => {
      const y = window.scrollY;
      const goingDown = y > lastY + 6;
      const goingUp = y < lastY - 6;
      if (goingDown || goingUp) lastY = y;
      const nav = navRef.current;
      const veil = veilRef.current;
      if (goingDown && y > 120 && nav) {
        nav.style.transform = 'translateY(-130%)';
        nav.style.opacity = '0';
        if (veil) veil.style.opacity = '0';
      } else if ((goingUp || y <= 120) && nav) {
        nav.style.transform = 'translateY(0)';
        nav.style.opacity = '1';
        if (veil) veil.style.opacity = '1';
      }
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      clearInterval(iv);
      window.removeEventListener('scroll', onScroll);
    };
  }, []);

  return (
    <>
      <div
        ref={veilRef}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          height: 120,
          zIndex: 90,
          pointerEvents: 'none',
          backdropFilter: 'blur(14px)',
          WebkitBackdropFilter: 'blur(14px)',
          background: 'linear-gradient(to bottom, rgba(14,14,13,0.85), rgba(14,14,13,0))',
          maskImage: 'linear-gradient(to bottom, black 25%, transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, black 25%, transparent 100%)',
          transition: 'opacity .35s ease',
        }}
      />
      <div
        ref={navRef}
        style={{
          position: 'fixed',
          top: 16,
          left: 0,
          right: 0,
          zIndex: 100,
          padding: '0 24px',
          transition:
            'transform .4s cubic-bezier(.22,1,.36,1), opacity .4s ease',
        }}
      >
        <header
          style={{
            maxWidth: 1160,
            margin: '0 auto',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 12px 10px 20px',
            border: '1.5px solid rgba(232,229,222,0.32)',
            borderRadius: 999,
            background: 'rgba(14,14,13,0.85)',
            backdropFilter: 'blur(14px)',
            boxShadow: '6px 6px 0 rgba(232,229,222,0.10)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span
              style={{
                display: 'inline-flex',
                width: 34,
                height: 34,
                border: '1.5px solid rgba(232,229,222,0.9)',
                borderRadius: '50%',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2.5,
              }}
            >
              {[
                { h: 8, d: '0s' },
                { h: 15, d: '.2s' },
                { h: 5, d: '.4s' },
              ].map((b, i) => (
                <span
                  key={i}
                  style={{
                    width: 2.5,
                    height: b.h,
                    background: CREAM,
                    borderRadius: 2,
                    transformOrigin: 'center',
                    animation: `logoWave 1.15s ease-in-out ${b.d} infinite`,
                  }}
                />
              ))}
            </span>
            <span style={{ fontFamily: SANS, fontSize: 20, fontWeight: 500, letterSpacing: '-0.01em' }}>
              Minutes
            </span>
            <span
              style={{
                fontFamily: MONO,
                fontSize: 11,
                letterSpacing: '0.08em',
                color: MUTE,
                paddingTop: 2,
              }}
            >
              Meeting intelligence
            </span>
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 24,
              fontFamily: MONO,
              fontSize: 11,
              letterSpacing: '0.05em',
              color: MUTE,
            }}
          >
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <span
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: '50%',
                  background: dotActive ? CREAM : DIM,
                  display: 'inline-block',
                  animation: dotPulse ? 'pulseDot 1.2s ease infinite' : 'none',
                }}
              />
              {status}
            </span>
            <span style={{ minWidth: 96, textAlign: 'right' }}>{clock}</span>
            {showReset && (
              <button
                data-hov="1"
                data-mag="1"
                onClick={onReset}
                style={{
                  background: 'none',
                  border: '1px solid rgba(232,229,222,0.35)',
                  color: CREAM,
                  fontFamily: MONO,
                  fontSize: 10,
                  letterSpacing: '0.06em',
                  padding: '9px 18px',
                  borderRadius: 999,
                  whiteSpace: 'nowrap',
                  transition: 'transform .3s cubic-bezier(.22,1,.36,1), background .2s, color .2s',
                }}
              >
                New session
              </button>
            )}
          </div>
        </header>
      </div>
    </>
  );
}
