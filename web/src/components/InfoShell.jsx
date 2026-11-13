import './pages.css';

export const INFO_PAGES = [
  { path: '/eval', label: 'Evaluation' },
  { path: '/usage', label: 'Usage' },
  { path: '/pipeline', label: 'How it works' },
];

export function pageForPath(pathname) {
  const clean = pathname.replace(/\/+$/, '') || '/';
  return INFO_PAGES.find((page) => page.path === clean)?.path || null;
}

export function InfoLinks({ className = '' }) {
  return (
    <nav className={`info-links ${className}`} aria-label="About this app">
      {INFO_PAGES.map((page) => <a key={page.path} href={page.path}>{page.label}</a>)}
    </nav>
  );
}

export default function InfoShell({ current, title, lede, children }) {
  return (
    <div className="info-page">
      <a className="info-skip" href="#info-main">Skip to content</a>
      <header className="info-bar">
        <a className="info-home" href="/" aria-label="Minutes home">
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <circle cx="12" cy="12" r="11" fill="none" stroke="currentColor" strokeWidth="1.4" />
            <path d="M8 9.5v5M12 7.5v9M16 10v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          <span>Minutes</span>
        </a>
        <nav className="info-tabs" aria-label="About this app">
          {INFO_PAGES.map((page) => (
            <a key={page.path} href={page.path} aria-current={page.path === current ? 'page' : undefined}>{page.label}</a>
          ))}
        </nav>
        <a className="info-back" href="/">Analyse a recording</a>
      </header>
      <main id="info-main" className="info-main">
        <div className="info-head">
          <h1>{title}</h1>
          {lede && <p className="info-lede">{lede}</p>}
        </div>
        {children}
      </main>
      <footer className="info-footer">
        <span>Minutes — upload, transcribe, ask.</span>
        <InfoLinks />
      </footer>
    </div>
  );
}

export function Section({ id, title, intro, children }) {
  return (
    <section className="info-section" id={id} aria-labelledby={`${id}-title`}>
      <div className="info-section-head">
        <h2 id={`${id}-title`}>{title}</h2>
        {intro && <p>{intro}</p>}
      </div>
      {children}
    </section>
  );
}

export const pct = (value, digits = 0) => (value == null ? '—' : `${(value * 100).toFixed(digits)}%`);
export const num = (value, digits = 3) => (value == null ? '—' : Number(value).toFixed(digits));
export const ms = (value) => (value == null ? '—' : value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} s` : `${Math.round(value)} ms`);
export const clock = (value) => (value == null ? '—' : `${Math.floor(value / 60000)}:${String(Math.floor(value / 1000) % 60).padStart(2, '0')}`);
// "openrouter:openrouter/nvidia/nemotron-3.5-lightning:free" → "nemotron-3.5-lightning"
export const shortModel = (model) => String(model || '').replace(/:free$/, '').split(':').pop().split('/').pop();
export const int = (value) => (value == null ? '—' : Number(value).toLocaleString('en-US'));

export function Bar({ value, max = 1, label }) {
  const width = Math.max(0, Math.min(1, (value ?? 0) / max)) * 100;
  return (
    <span className="info-bar-track" role="img" aria-label={label}>
      <span className="info-bar-fill" style={{ width: `${width}%` }} />
    </span>
  );
}
