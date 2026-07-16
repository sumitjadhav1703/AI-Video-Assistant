import { useEffect, useRef } from 'react';

// Grain film + custom cursor (dot + ring). The cursor only activates on devices
// with a real pointer; touch devices keep their native behaviour untouched.
export default function Overlays() {
  const dotRef = useRef(null);
  const ringRef = useRef(null);

  useEffect(() => {
    if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return undefined;
    document.body.classList.add('custom-cursor');

    const dot = dotRef.current;
    const ring = ringRef.current;
    let hovOn = false;
    let lastMag = null;

    const move = (e) => {
      const x = e.clientX;
      const y = e.clientY;
      if (dot) dot.style.transform = `translate(${x - 4}px,${y - 4}px)`;
      const scale = hovOn ? 2.1 : 1;
      if (ring) ring.style.transform = `translate(${x - 17}px,${y - 17}px) scale(${scale})`;

      const mag = e.target && e.target.closest ? e.target.closest('[data-mag]') : null;
      if (mag) {
        const r = mag.getBoundingClientRect();
        mag.style.transform = `translate(${(x - r.left - r.width / 2) * 0.22}px,${
          (y - r.top - r.height / 2) * 0.22
        }px)`;
        lastMag = mag;
      } else if (lastMag) {
        lastMag.style.transform = 'translate(0px, 0px)';
        lastMag = null;
      }
    };
    const over = (e) => {
      hovOn = !!(e.target && e.target.closest && e.target.closest('[data-hov]'));
    };

    document.addEventListener('mousemove', move, { passive: true });
    document.addEventListener('mouseover', over, { passive: true });
    return () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseover', over);
      document.body.classList.remove('custom-cursor');
    };
  }, []);

  return (
    <>
      <div
        style={{
          position: 'fixed',
          inset: '-40px',
          zIndex: 9600,
          pointerEvents: 'none',
          opacity: 0.06,
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='240'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/%3E%3C/filter%3E%3Crect width='240' height='240' filter='url(%23n)'/%3E%3C/svg%3E\")",
          backgroundSize: '240px 240px',
        }}
      />
      <div
        ref={ringRef}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: 34,
          height: 34,
          border: '1px solid rgba(255,255,255,0.65)',
          borderRadius: '50%',
          pointerEvents: 'none',
          zIndex: 9999,
          mixBlendMode: 'difference',
          transform: 'translate(-200px,-200px)',
          transition: 'transform .22s cubic-bezier(.22,1,.36,1)',
        }}
      />
      <div
        ref={dotRef}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: 8,
          height: 8,
          background: '#ffffff',
          borderRadius: '50%',
          pointerEvents: 'none',
          zIndex: 9999,
          mixBlendMode: 'difference',
          transform: 'translate(-200px,-200px)',
        }}
      />
    </>
  );
}
