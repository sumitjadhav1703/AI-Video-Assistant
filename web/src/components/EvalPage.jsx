import { useMemo, useState } from 'react';
import data from '../data/evaluation.json';
import InfoShell, { Bar, Section, clock, int, ms, num, pct, shortModel } from './InfoShell';

const CATEGORY_LABELS = {
  direct_factual: 'Direct fact', numerical_date: 'Number or date', named_entity: 'Named entity',
  multi_passage: 'Multi-passage', multi_hop: 'Multi-hop', unanswerable: 'Unanswerable',
  ambiguous: 'Ambiguous', misleading: 'False premise',
};
const STAGE_LABELS = { generation: 'Final answer (top 4 passages)', retrieval_pre_rerank: 'Before reranking (top 12)', sanity: 'Judge sanity controls' };
const LATENCY_LABELS = {
  dense_retrieval: 'Dense search (pgvector)', sparse_retrieval: 'BM25 search', rrf: 'Rank fusion (RRF)',
  rerank: 'TinyBERT rerank', generation: 'Answer generation (per attempt)', end_to_end: 'Whole question, end to end',
};

function Figures() {
  const gen = data.deepeval.generation;
  const det = data.deterministic;
  const items = [
    ['Faithfulness', num(gen.Faithfulness.avg_score), `${gen.Faithfulness.passed}/${gen.Faithfulness.n_scored} answers stayed inside their evidence`],
    ['Answer relevancy', num(gen['Answer Relevancy'].avg_score), `${gen['Answer Relevancy'].passed}/${gen['Answer Relevancy'].n_scored} passed the 0.7 threshold`],
    ['Right answer or abstention', `${Math.round(det.behavior_accuracy * 45)}/45`, 'Both misses were service errors, not wrong answers'],
    ['Unanswerable questions', `${det.abstention.true_abstentions}/6`, 'Correctly refused; zero false refusals on 32 answerable'],
    ['Valid citations', `${Math.round(det.citation_validity * det.citations_total)}/${det.citations_total}`, 'Exact quote, right passage, right timestamp'],
    ['Retrieval recall@4', num(data.retrieval.variants.find((v) => v.variant === 'hybrid_rerank').recall), `Gold evidence in the top 4, over ${data.retrieval.n} questions`],
    ['Answer time, p95', ms(data.latency.warm.end_to_end.p95), `Median ${ms(data.latency.warm.end_to_end.p50)}`],
    ['Judge cost', `$${data.cost?.total_usd.toFixed(2) ?? '—'}`, `${int(data.cost?.total_calls)} paid judge calls; the app itself used free models`],
  ];
  return (
    <dl className="info-figures">
      {items.map(([label, value, note]) => (
        <div className="info-figure" key={label}>
          <dt>{label}</dt>
          <dd><span className="info-num">{value}</span><span className="info-note">{note}</span></dd>
        </div>
      ))}
    </dl>
  );
}

function DeepEvalTable({ stage }) {
  const rows = Object.entries(data.deepeval[stage]);
  return (
    <div className="info-table-wrap">
      <table className="info-table">
        <caption>{STAGE_LABELS[stage]}. {stage === 'sanity'
          ? 'Deliberately wrong answers; a trustworthy judge must score them near 0.'
          : 'Scored 0–1 by the judge model; average is the primary signal.'}</caption>
        <thead><tr><th scope="col">Metric</th><th scope="col" className="r">Average</th><th scope="col">Distribution</th><th scope="col" className="r">Threshold</th><th scope="col" className="r">Passed</th><th scope="col" className="r">Errors</th></tr></thead>
        <tbody>
          {rows.map(([name, s]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td className="r info-num">{num(s.avg_score)}</td>
              <td><Bar value={s.avg_score} label={`${name} average ${num(s.avg_score)}`} /></td>
              <td className="r info-num info-dim">{s.threshold}</td>
              <td className="r info-num">{s.passed}/{s.n_scored}</td>
              <td className="r info-num info-dim">{s.errors}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Retrieval() {
  const r = data.retrieval;
  return (
    <div className="info-table-wrap">
      <table className="info-table">
        <caption>Same {r.n} questions, same captured requests; each variant re-ranked from what the app actually retrieved. “vs production” is the mean difference in recall@4 with a 95% bootstrap interval; an interval that contains 0 is not a real difference.</caption>
        <thead><tr><th scope="col">Retrieval variant</th><th scope="col" className="r">Recall@4</th><th scope="col">Recall</th><th scope="col" className="r">MRR</th><th scope="col" className="r">nDCG@4</th><th scope="col" className="r">vs production</th></tr></thead>
        <tbody>
          {r.variants.map((v) => {
            const ci = v.vs_production_recall;
            const real = ci && (ci.ci95[0] > 0 || ci.ci95[1] < 0);
            return (
              <tr key={v.variant}>
                <th scope="row">{v.label}</th>
                <td className="r info-num">{num(v.recall)}</td>
                <td><Bar value={v.recall} label={`Recall ${num(v.recall)}`} /></td>
                <td className="r info-num">{num(v.mrr)}</td>
                <td className="r info-num">{num(v.ndcg)}</td>
                <td className={`r info-num ${real ? (ci.mean_diff < 0 ? 'info-fail' : 'info-pass') : 'info-dim'}`}>
                  {ci ? `${ci.mean_diff >= 0 ? '+' : ''}${ci.mean_diff.toFixed(3)} [${ci.ci95[0].toFixed(3)}, ${ci.ci95[1].toFixed(3)}]` : 'baseline'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Behaviour() {
  const rows = Object.entries(data.deterministic.behavior_by_category);
  return (
    <div className="info-table-wrap">
      <table className="info-table">
        <caption>Deterministic checks, no judge involved: did the app answer when it should, refuse when it should, and correct false premises?</caption>
        <thead><tr><th scope="col">Question type</th><th scope="col" className="r">Correct</th><th scope="col">Rate</th></tr></thead>
        <tbody>
          {rows.map(([category, s]) => (
            <tr key={category}>
              <th scope="row">{CATEGORY_LABELS[category] || category}</th>
              <td className="r info-num">{s.correct}/{s.n}</td>
              <td><Bar value={s.accuracy} label={`${pct(s.accuracy)} correct`} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Latency() {
  const warm = data.latency.warm;
  return (
    <div className="info-table-wrap">
      <table className="info-table">
        <caption>{data.latency.note}</caption>
        <thead><tr><th scope="col">Stage</th><th scope="col" className="r">p50</th><th scope="col" className="r">p95</th><th scope="col" className="r">p99</th><th scope="col" className="r">Samples</th></tr></thead>
        <tbody>
          {Object.entries(LATENCY_LABELS).map(([key, label]) => warm[key] && (
            <tr key={key}>
              <th scope="row">{label}</th>
              <td className="r info-num">{ms(warm[key].p50)}</td>
              <td className="r info-num">{ms(warm[key].p95)}</td>
              <td className="r info-num">{ms(warm[key].p99)}</td>
              <td className="r info-num info-dim">{warm[key].n}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Cost() {
  const c = data.cost;
  if (!c) return <p className="info-status">Judge cost ledger not available in this build.</p>;
  return (
    <div className="info-table-wrap">
      <table className="info-table">
        <caption>Judge: {c.model}, a paid model used only to grade the answers. The app under test ran on free models ($0).</caption>
        <thead><tr><th scope="col">Run</th><th scope="col" className="r">Calls</th><th scope="col" className="r">Input tokens</th><th scope="col" className="r">Output tokens</th><th scope="col" className="r">Cost</th></tr></thead>
        <tbody>
          {c.runs.map((r) => (
            <tr key={r.label}>
              <th scope="row">{r.label}</th>
              <td className="r info-num">{int(r.calls)}</td>
              <td className="r info-num">{int(r.input_tokens)}</td>
              <td className="r info-num">{int(r.output_tokens)}</td>
              <td className="r info-num">${r.usd.toFixed(4)}</td>
            </tr>
          ))}
          <tr>
            <th scope="row">Total</th>
            <td className="r info-num">{int(c.total_calls)}</td>
            <td className="r info-num">{int(c.total_input_tokens)}</td>
            <td className="r info-num">{int(c.total_output_tokens)}</td>
            <td className="r info-num">${c.total_usd.toFixed(2)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function verdict(c) {
  if (c.error) return { text: 'Service error', cls: 'info-fail' };
  if (!c.behavior) return { text: '—', cls: 'info-dim' };
  if (!c.behavior.correct) return { text: c.behavior.reason, cls: 'info-fail' };
  return { text: c.abstained ? 'Correctly refused' : 'Correct', cls: 'info-pass' };
}

function QuestionExplorer() {
  const [category, setCategory] = useState('all');
  const [open, setOpen] = useState(null);
  const categories = useMemo(() => ['all', ...new Set(data.cases.map((c) => c.category))], []);
  const shown = data.cases.filter((c) => category === 'all' || c.category === category);
  return (
    <>
      <div className="info-chips" role="group" aria-label="Filter by question type">
        {categories.map((c) => (
          <button key={c} type="button" aria-pressed={category === c} onClick={() => setCategory(c)}>
            {c === 'all' ? `All ${data.cases.length}` : `${CATEGORY_LABELS[c] || c} ${data.cases.filter((x) => x.category === c).length}`}
          </button>
        ))}
      </div>
      <div className="info-qlist">
        {shown.map((c) => {
          const v = verdict(c);
          const expanded = open === c.id;
          return (
            <div className="info-q" key={c.id}>
              <button type="button" aria-expanded={expanded} aria-controls={`q-${c.id}`} onClick={() => setOpen(expanded ? null : c.id)}>
                <span className="info-q-id">{c.id.replace('NASA-', '')}</span>
                <span>{c.question}</span>
                <span className={`info-q-verdict ${v.cls}`}>{v.text}</span>
              </button>
              {expanded && (
                <div className="info-q-body" id={`q-${c.id}`}>
                  <div><h3>Expected</h3><p>{c.expected_answer}</p></div>
                  <div><h3>The app answered{c.model ? ` (${shortModel(c.model)})` : ''}</h3><p>{c.answer || (c.error ? 'No answer: every model output was rejected by the citation check (HTTP 503).' : '—')}</p></div>
                  {c.citations.length > 0 && (
                    <div><h3>Cited evidence</h3>
                      {c.citations.map((cite, i) => <p key={i}><q>{cite.text}</q> <span className="info-dim info-num">{clock(cite.start_ms)}–{clock(cite.end_ms)}</span></p>)}
                    </div>
                  )}
                  {Object.entries(c.judge).map(([stage, metrics]) => (
                    <div key={stage}><h3>Judge — {STAGE_LABELS[stage]}</h3>
                      <div className="info-table-wrap"><table className="info-table"><tbody>
                        {metrics.map((m) => (
                          <tr key={m.metric}>
                            <th scope="row">{m.metric}</th>
                            <td className={`r info-num ${m.error ? 'info-dim' : m.passed ? 'info-pass' : 'info-fail'}`}>{m.error ? 'error' : num(m.score, 2)}</td>
                            <td>{m.error || m.reason}</td>
                          </tr>
                        ))}
                      </tbody></table></div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

function Future() {
  const f = data.future;
  if (!f) return null;
  const d = f.deterministic;
  return (
    <div className="info-callout">
      <p style={{ marginTop: 0 }}><strong>Not active in the app.</strong> A second version of the answer pipeline (looser quote matching, sentence chunking, a new prompt) was tested against v1 on {f.cases_compared} paired questions with the same model.</p>
      <p>Service errors fell from <strong>{d.request_errors_503['v1-pinned']} to {d.request_errors_503['v2-iter1']}</strong> and faithfulness stayed at {num(f.deepeval.Faithfulness['v1-pinned'])}, but answers got longer and p95 latency rose from {ms(f.latency['v1-pinned'].p95)} to {ms(f.latency['v2-iter1'].p95)}, failing the pre-registered latency gate. It is parked in <code>{f.path}</code> until it passes.</p>
    </div>
  );
}

export default function EvalPage() {
  return (
    <InfoShell
      current="/eval"
      title="How well it answers"
      lede={`45 hand-checked questions about a public-domain NASA talk (${data.source.duration}), answered by the real pipeline and graded twice: by deterministic checks and by an LLM judge. Every number below comes from the run, including the failures.`}
    >
      <Figures />
      <Section id="judge" title="Judged quality" intro={`DeepEval ${data.deepeval_version} with ${data.judge} as judge. Only the 32 questions that have an answer are judged; refusals are checked deterministically below.`}>
        <div style={{ display: 'grid', gap: 24 }}>
          <DeepEvalTable stage="generation" />
          <DeepEvalTable stage="retrieval_pre_rerank" />
          <DeepEvalTable stage="sanity" />
        </div>
      </Section>
      <Section id="behaviour" title="Answering, refusing and citing" intro={`${data.deterministic.citations_total} citations checked, all exact quotes from the passage the model was given. ${data.deterministic.adversarial_cases} malformed model outputs were fed to the validator and all handled safely.`}>
        <Behaviour />
      </Section>
      <Section id="retrieval" title="Which retrieval works best" intro="Production combines dense vectors and BM25 keywords, fuses them, and reranks with a small cross-encoder. Each part was switched off to see what it contributes.">
        <Retrieval />
      </Section>
      <Section id="latency" title="How fast" intro="Retrieval takes milliseconds; nearly all of the wait is the language model writing the answer.">
        <Latency />
      </Section>
      <Section id="questions" title="Every question" intro="Open any question to see the expected answer, what the app said, the evidence it cited and the judge’s reasoning.">
        <QuestionExplorer />
      </Section>
      <Section id="cost" title="What the evaluation cost" intro="Grading uses a stronger paid model with a hard spending cap; the app being graded used only free routes.">
        <Cost />
      </Section>
      <Section id="method" title="Method and limits">
        <div className="info-two">
          <div className="info-prose">
            <ul>
              <li><strong>Source:</strong> <a href={data.source.url} target="_blank" rel="noreferrer">{data.source.title}</a>, {data.source.speaker} ({data.source.licence}).</li>
              <li><strong>Questions:</strong> 45 across 8 types, including 6 unanswerable and 4 with false premises. Every evidence quote was verified as an exact substring of the transcript.</li>
              <li><strong>Answer models:</strong> {data.generators.map(shortModel).join(', ')} (free routes; the app falls back between them).</li>
              <li><strong>Judge:</strong> {data.judge}, paid, capped; 4 deliberately wrong controls all scored 0.</li>
            </ul>
          </div>
          <div className="info-prose">
            <ul>
              <li>One 13.5-minute source with {data.source.chunks} passages, so absolute retrieval scores are optimistic.</li>
              <li>One judge, one run; judge noise is not yet measured.</li>
              <li>Free answer models change with availability; the model behind each answer is shown per question.</li>
              <li>Audio transcription is not part of this score; the official captions stood in for it.</li>
            </ul>
          </div>
        </div>
      </Section>
      <Section id="next" title="Tried, not shipped">
        <Future />
      </Section>
    </InfoShell>
  );
}
