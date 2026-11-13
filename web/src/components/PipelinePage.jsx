import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import InfoShell from './InfoShell';
import { FLOW_TABS, edgePath, getFlow } from './pipelineFlows';
import './PipelinePage.css';

const TRAVEL_MS = 1100;
const DWELL_MS = 2600;
const NODE_W = 168;
const NODE_H = 66;

function useMedia(query) {
  const [match, setMatch] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatch(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [query]);
  return match;
}

const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

export default function PipelinePage() {
  const reduced = useMedia('(prefers-reduced-motion: reduce)');
  const mobile = useMedia('(max-width: 720px)');
  const [flowId, setFlowId] = useState('processing');
  const [scenario, setScenario] = useState('answerable');
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(!reduced);
  const [speed, setSpeed] = useState(1);
  const [arrived, setArrived] = useState(true);

  const flow = useMemo(() => getFlow(flowId, scenario), [flowId, scenario]);
  const layout = mobile ? 'mobile' : 'desktop';
  const width = mobile ? 360 : 1000;
  const pos = useCallback((node) => (mobile ? { x: node.mx, y: node.my } : { x: node.x, y: node.y }), [mobile]);
  // Fit the drawing to its nodes so the canvas carries no dead space above or below.
  const [top, height] = useMemo(() => {
    const ys = flow.nodes.map((n) => pos(n).y);
    const min = Math.min(...ys) - NODE_H / 2 - 28;
    return [min, Math.max(...ys) + NODE_H / 2 + 28 - min];
  }, [flow, pos]);
  const nodes = useMemo(() => Object.fromEntries(flow.nodes.map((n) => [n.id, n])), [flow]);
  const current = flow.steps[Math.min(step, flow.steps.length - 1)];

  const done = useMemo(() => {
    const seen = new Set();
    flow.steps.slice(0, step + 1).forEach((s, i) => {
      seen.add(s.node);
      if (s.parallel) s.edges.forEach(([, to]) => seen.add(to));
      if (i === step && !arrived) seen.delete(s.node);
    });
    return seen;
  }, [flow, step, arrived]);
  const travelled = useMemo(() => {
    const seen = new Set();
    flow.steps.slice(0, step + 1).forEach((s, i) => s.edges.forEach(([a, b]) => { if (i < step || arrived) seen.add(`${a}-${b}`); }));
    return seen;
  }, [flow, step, arrived]);

  const pathRefs = useRef({});
  const packetRefs = useRef([]);
  const frame = useRef(0);

  // Move this step's packets along their edges; nodes light up when the packets arrive.
  useEffect(() => {
    cancelAnimationFrame(frame.current);
    const edges = current.edges;
    if (!edges.length || reduced) {
      setArrived(true);
      edges.forEach((edge, i) => {
        const path = pathRefs.current[`${edge[0]}-${edge[1]}`];
        const packet = packetRefs.current[i];
        if (path && packet) {
          const end = path.getPointAtLength(path.getTotalLength());
          packet.setAttribute('transform', `translate(${end.x} ${end.y})`);
        }
      });
      return undefined;
    }
    setArrived(false);
    const started = performance.now();
    const duration = TRAVEL_MS / speed;
    const tick = (now) => {
      const t = Math.min(1, (now - started) / duration);
      edges.forEach((edge, i) => {
        const path = pathRefs.current[`${edge[0]}-${edge[1]}`];
        const packet = packetRefs.current[i];
        if (!path || !packet) return;
        const point = path.getPointAtLength(path.getTotalLength() * easeInOut(t));
        packet.setAttribute('transform', `translate(${point.x} ${point.y})`);
      });
      if (t < 1) frame.current = requestAnimationFrame(tick);
      else setArrived(true);
    };
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [current, speed, reduced, layout]);

  // Autoplay: dwell on each arrived step, then advance; pause at the end.
  useEffect(() => {
    if (!playing || !arrived) return undefined;
    if (step >= flow.steps.length - 1) {
      const timer = setTimeout(() => setPlaying(false), DWELL_MS / speed);
      return () => clearTimeout(timer);
    }
    const timer = setTimeout(() => setStep((s) => s + 1), DWELL_MS / speed);
    return () => clearTimeout(timer);
  }, [playing, arrived, step, flow, speed]);

  const switchFlow = (id) => { setFlowId(id); setStep(0); setPlaying(!reduced); };
  const switchScenario = (s) => { setScenario(s); setStep(0); setPlaying(!reduced); };
  const go = (next) => { setStep(Math.max(0, Math.min(flow.steps.length - 1, next))); };
  const restart = () => { setStep(0); setPlaying(true); };
  const atEnd = step >= flow.steps.length - 1;

  const nodeW = NODE_W;

  return (
    <InfoShell
      current="/pipeline"
      title="How it works"
      lede="Follow a real recording and a real question through the system. Each step shows what goes in, what comes out, how long it took in a measured run, and what happens when something fails."
    >
      <div className="pipe-toolbar">
        <div className="pipe-tabs" role="tablist" aria-label="Choose a flow">
          {FLOW_TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={flowId === t.id} onClick={() => switchFlow(t.id)}>{t.label}</button>
          ))}
        </div>
        {flowId === 'chat' && (
          <div className="pipe-scenario" role="group" aria-label="Question type">
            <button type="button" aria-pressed={scenario === 'answerable'} onClick={() => switchScenario('answerable')}>Answerable question</button>
            <button type="button" aria-pressed={scenario === 'unanswerable'} onClick={() => switchScenario('unanswerable')}>Not in the recording</button>
          </div>
        )}
      </div>

      <div className="pipe-stage">
        <figure className="pipe-canvas" aria-label={`${flow.label} diagram`}>
          <svg viewBox={`0 ${top} ${width} ${height}`} role="img" aria-labelledby="pipe-svg-title">
            <title id="pipe-svg-title">{`${flow.label}: ${flow.steps.map((s) => nodes[s.node].label).join(', then ')}`}</title>
            <defs>
              <radialGradient id="pipe-glow">
                <stop offset="0%" stopColor="#e8e5de" stopOpacity=".55" />
                <stop offset="100%" stopColor="#e8e5de" stopOpacity="0" />
              </radialGradient>
            </defs>
            <g className="pipe-edges">
              {flow.edges.map(([a, b]) => {
                const key = `${a}-${b}`;
                const inactive = nodes[b].outcome && nodes[b].outcome !== scenario;
                return (
                  <path
                    key={key}
                    ref={(el) => { pathRefs.current[key] = el; }}
                    d={edgePath(pos(nodes[a]), pos(nodes[b]))}
                    className={`pipe-edge${travelled.has(key) ? ' is-done' : ''}${current.edges.some(([x, y]) => `${x}-${y}` === key) ? ' is-live' : ''}${inactive ? ' is-muted' : ''}`}
                  />
                );
              })}
            </g>
            <g className="pipe-packets" aria-hidden="true">
              {current.edges.map((edge, i) => (
                <g key={`${step}-${edge.join('-')}`} ref={(el) => { packetRefs.current[i] = el; }} className={arrived ? 'is-landed' : ''}>
                  <circle r="22" fill="url(#pipe-glow)" />
                  <circle r="6" className="pipe-packet-core" />
                </g>
              ))}
            </g>
            <g className="pipe-nodes">
              {flow.nodes.map((n) => {
                const p = pos(n);
                const index = flow.steps.findIndex((s) => s.node === n.id || (s.parallel && s.edges.some(([, to]) => to === n.id)));
                const isCurrent = (current.node === n.id || (current.parallel && current.edges.some(([, to]) => to === n.id))) && arrived;
                const muted = n.outcome && n.outcome !== scenario;
                const state = isCurrent ? 'is-current' : done.has(n.id) ? 'is-done' : '';
                return (
                  <g
                    key={n.id}
                    className={`pipe-node ${state}${muted ? ' is-muted' : ''}`}
                    transform={`translate(${p.x - nodeW / 2} ${p.y - NODE_H / 2})`}
                    onClick={() => index >= 0 && !muted && (setPlaying(false), go(index))}
                  >
                    <rect width={nodeW} height={NODE_H} rx="14" />
                    <text x={nodeW / 2} y="29" className="pipe-node-label">{n.label}</text>
                    <text x={nodeW / 2} y="49" className="pipe-node-sub">{n.sub}</text>
                  </g>
                );
              })}
            </g>
          </svg>
          <figcaption className="pipe-payload" aria-hidden="true">
            <span className="pipe-payload-label">Carrying</span>
            <span key={`${flowId}-${scenario}-${step}`} className="pipe-payload-value">{current.payload}</span>
          </figcaption>
        </figure>

        <aside className="pipe-detail" aria-live="polite">
          <div className="pipe-detail-text">
            <h2>{current.title}</h2>
            <p>{current.what}</p>
          </div>
          <div>
          <dl>
            {current.measured !== '—' && <div><dt>Measured</dt><dd>{current.measured}</dd></div>}
            {current.fails !== '—' && <div><dt>When it goes wrong</dt><dd>{current.fails}</dd></div>}
          </dl>
          <div className="pipe-controls">
            <button type="button" onClick={() => { setPlaying(false); go(step - 1); }} disabled={step === 0} aria-label="Previous step">
              <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M12.5 4.5 7 10l5.5 5.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
            {atEnd && !playing ? (
              <button type="button" className="pipe-primary" onClick={restart}>Replay</button>
            ) : (
              <button type="button" className="pipe-primary" onClick={() => setPlaying((p) => !p)} aria-pressed={playing}>
                {playing ? 'Pause' : 'Play'}
              </button>
            )}
            <button type="button" onClick={() => { setPlaying(false); go(step + 1); }} disabled={atEnd} aria-label="Next step">
              <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M7.5 4.5 13 10l-5.5 5.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
            <span className="pipe-count">{step + 1} / {flow.steps.length}</span>
            <button type="button" className="pipe-speed" onClick={() => setSpeed((s) => (s === 1 ? 2 : s === 2 ? 0.5 : 1))} aria-label={`Speed ${speed}×, change speed`}>
              {speed}×
            </button>
          </div>
          </div>
        </aside>
      </div>

      <ol className="pipe-steps" aria-label="All steps">
        {flow.steps.map((s, i) => (
          <li key={`${flowId}-${scenario}-${i}`}>
            <button type="button" aria-current={i === step ? 'step' : undefined} className={i < step ? 'is-done' : ''} onClick={() => { setPlaying(false); go(i); }}>
              <span className="pipe-step-n">{i + 1}</span>
              <span>{s.title}</span>
            </button>
          </li>
        ))}
      </ol>
    </InfoShell>
  );
}
