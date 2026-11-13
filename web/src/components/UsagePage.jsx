import { useEffect, useState } from 'react';
import { getUsage } from '../api';
import data from '../data/evaluation.json';
import InfoShell, { Section, int, ms, shortModel } from './InfoShell';

const TASK_LABELS = { title: 'Title', summary: 'Summary', extract: 'Findings', chat: 'Chat answers' };
const usage = data.usage;

function Allowance({ live, state }) {
  if (state === 'loading') return <p className="info-status" role="status">Checking today’s allowance…</p>;
  if (!live) {
    return (
      <p className="info-status" role="status">
        Live limits are unavailable right now (the free backend may be asleep). The measured usage below still applies.
      </p>
    );
  }
  const { remaining, limits, resets_at: resets, mode } = live;
  if (mode === 'sample' || !remaining) {
    return <p className="info-status" role="status">Live analysis is paused on this deployment, so nothing is counted today.</p>;
  }
  const items = [
    ['Analyses left today', remaining.analyses_today, `of ${limits.analyses_per_visitor_day} per visitor · ${limits.analyses_all_visitors_day} across everyone`],
    ['Questions left today', remaining.chats_today, `of ${limits.chats_per_visitor_day} per visitor · ${limits.chats_per_session_day} per recording`],
    ['Questions this minute', remaining.chats_this_minute, `of ${limits.chats_per_visitor_minute} per minute`],
    ['Largest upload', `${limits.max_upload_mib} MiB`, 'First 10 minutes are analysed'],
  ];
  return (
    <>
      <dl className="info-figures">
        {items.map(([label, value, note]) => (
          <div className="info-figure" key={label}>
            <dt>{label}</dt>
            <dd><span className="info-num">{value}</span><span className="info-note">{note}</span></dd>
          </div>
        ))}
      </dl>
      {resets && (
        <p className="info-status" style={{ marginTop: 14 }}>
          Counts reset at {new Date(resets).toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })} (midnight UTC). Limits keep a free demo free for everyone; they are counted per connection, never per account.
        </p>
      )}
    </>
  );
}

function Models({ live }) {
  if (!live) return <p className="info-status">The model list is read live from the backend and is unavailable right now.</p>;
  const { generation, embeddings, speech_to_text: speech } = live.models;
  const chain = (routes) => routes.map((r, i) => (
    <span key={`${r.route || r.model}-${i}`}>{i > 0 && <span className="info-dim"> → </span>}{shortModel(r.model)}{r.provider ? <span className="info-dim"> ({r.provider.replace('_nim', '')})</span> : null}</span>
  ));
  return (
    <div className="info-table-wrap">
      <table className="info-table">
        <caption>First model in each row is tried first; if it is rate-limited or its output fails validation, the next one answers. All are free routes; paid routes are never offered to visitors.</caption>
        <thead><tr><th scope="col">Job</th><th scope="col">Models, in fallback order</th></tr></thead>
        <tbody>
          <tr><th scope="row">Transcription</th><td>{speech.length ? chain(speech) : '—'}</td></tr>
          {Object.entries(generation).map(([task, routes]) => (
            <tr key={task}><th scope="row">{TASK_LABELS[task] || task}</th><td>{routes.length ? chain(routes) : '—'}</td></tr>
          ))}
          <tr><th scope="row">Search embeddings</th><td>{embeddings.length ? chain(embeddings) : '—'}</td></tr>
          <tr><th scope="row">Reranking</th><td>ms-marco-TinyBERT-L-2-v2 <span className="info-dim">(runs locally in the server, no API)</span></td></tr>
        </tbody>
      </table>
    </div>
  );
}

function PerAnalysis() {
  if (!usage) return null;
  const a = usage.analysis;
  return (
    <div className="info-table-wrap">
      <table className="info-table">
        <caption>Measured {usage.measured_at} on a {a.audio_seconds}-second recording; time to result {ms(a.time_to_result_ms)}. Token counts are what each provider reported. Longer recordings use more transcription time and more tokens.</caption>
        <thead><tr><th scope="col">Step</th><th scope="col">Model</th><th scope="col" className="r">Time</th><th scope="col" className="r">Tokens in</th><th scope="col" className="r">Tokens out</th></tr></thead>
        <tbody>
          {a.stages.map((s) => (
            <tr key={s.stage}>
              <th scope="row">{s.stage}</th>
              <td>{s.model}{s.note && <div className="info-dim" style={{ fontSize: 12, marginTop: 2 }}>{s.note}</div>}</td>
              <td className="r info-num">{ms(s.elapsed_ms)}</td>
              <td className="r info-num">{int(s.input_tokens)}</td>
              <td className="r info-num">{int(s.output_tokens)}</td>
            </tr>
          ))}
          <tr><th scope="row">Language-model total</th><td className="info-dim">title + summary + findings</td><td /><td className="r info-num">{int(a.llm_tokens_total.input)}</td><td className="r info-num">{int(a.llm_tokens_total.output)}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function PerQuestion() {
  if (!usage) return null;
  const { short_clip: s, full_talk: f } = usage.chat;
  return (
    <div className="info-table-wrap">
      <table className="info-table">
        <caption>Each question sends the four best-matching passages and the question to one model. Bigger passages mean more input tokens; the answer itself is short.</caption>
        <thead><tr><th scope="col">Recording</th><th scope="col" className="r">Tokens in</th><th scope="col" className="r">Tokens out</th><th scope="col" className="r">Answer time</th></tr></thead>
        <tbody>
          <tr><th scope="row">{s.description}</th><td className="r info-num">{int(s.calls[0].input_tokens)}</td><td className="r info-num">≈{int(Math.round((s.calls[0].output_tokens + s.calls[1].output_tokens) / 2))}</td><td className="r info-num">{ms(s.calls[1].elapsed_ms)}</td></tr>
          <tr><th scope="row">{f.description}</th><td className="r info-num">≈{int(f.input_tokens_median)}</td><td className="r info-num">≈{int(f.output_tokens_median)}</td><td className="r info-num">{ms(f.end_to_end_ms_p50)} <span className="info-dim">(p95 {ms(f.end_to_end_ms_p95)})</span></td></tr>
        </tbody>
      </table>
    </div>
  );
}

export default function UsagePage() {
  const [live, setLive] = useState(null);
  const [state, setState] = useState('loading');
  useEffect(() => {
    const controller = new AbortController();
    getUsage(controller.signal)
      .then((body) => { setLive(body); setState('ready'); })
      .catch(() => { if (!controller.signal.aborted) setState('unavailable'); });
    return () => controller.abort();
  }, []);

  return (
    <InfoShell
      current="/usage"
      title="What it uses, and what you have left"
      lede="Minutes runs on free model tiers, so every visitor shares a small daily allowance. Here is how much you can still try today, which models do the work, and how many tokens each step really uses."
    >
      <Section id="allowance" title="Your allowance today" intro="Read live from the server for your connection.">
        <Allowance live={live} state={state} />
      </Section>
      <Section id="models" title="Models doing the work" intro="Each job has a chain of free models. The server picks the first one with capacity whose answer passes validation.">
        <Models live={live} />
      </Section>
      <Section id="analysis" title="One analysis, step by step" intro="Uploading a recording runs six steps once; after that, questions only touch search and one model call.">
        <PerAnalysis />
      </Section>
      <Section id="question" title="One question" intro="Search, fusion and reranking are local and take milliseconds; the tokens below are the single model call.">
        <PerQuestion />
      </Section>
      {usage && (
        <Section id="cost" title="Cost and safeguards">
          <div className="info-two">
            <div className="info-callout">
              <strong>${usage.cost_usd.provider_calls} per analysis or question.</strong> {usage.cost_usd.note}
            </div>
            <div className="info-callout">
              <strong>Pessimistic budgeting.</strong> {usage.reservations.note} A single recording may use at most {usage.reservations.job_lifetime_budget.attempts} model calls, {int(usage.reservations.job_lifetime_budget.input_tokens)} input and {int(usage.reservations.job_lifetime_budget.output_tokens)} output tokens.
            </div>
          </div>
        </Section>
      )}
    </InfoShell>
  );
}
