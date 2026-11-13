// Data for the /pipeline explainer. Positions: desktop (x, y) in a 1000×420 box; mobile (mx, my) in a 360×N box.
// Example payloads and timings come from the measured local run (docs/usage_measurement.json, 13 Nov 2026).

const processing = {
  id: 'processing',
  label: 'Processing a recording',
  nodes: [
    { id: 'upload', label: 'Upload', sub: 'your recording', x: 100, y: 110, mx: 180, my: 50 },
    { id: 'audio', label: 'Audio', sub: 'ffmpeg', x: 300, y: 110, mx: 180, my: 155 },
    { id: 'transcribe', label: 'Transcribe', sub: 'Whisper', x: 500, y: 110, mx: 180, my: 260 },
    { id: 'chunk', label: 'Chunk', sub: '500 characters', x: 700, y: 110, mx: 180, my: 365 },
    { id: 'notes', label: 'Write notes', sub: 'title · summary · findings', x: 900, y: 310, mx: 180, my: 470 },
    { id: 'embed', label: 'Embed', sub: 'meaning → numbers', x: 700, y: 310, mx: 180, my: 575 },
    { id: 'index', label: 'Index', sub: 'Postgres + pgvector', x: 500, y: 310, mx: 180, my: 680 },
    { id: 'ready', label: 'Ready', sub: 'ask anything', x: 300, y: 310, mx: 180, my: 785 },
  ],
  edges: [['upload', 'audio'], ['audio', 'transcribe'], ['transcribe', 'chunk'], ['chunk', 'notes'],
    ['notes', 'embed'], ['embed', 'index'], ['index', 'ready']],
  steps: [
    { node: 'upload', edges: [], payload: 'project_review.mp3 · 165 KB',
      title: 'You upload a recording',
      what: 'MP3, WAV, MP4 or MOV up to 25 MiB. The file streams to the server in pieces, so a large upload never sits in memory.',
      measured: 'Instant for a 165 KB clip', fails: 'Wrong type, empty or oversized files are refused before anything is counted against your allowance.' },
    { node: 'audio', edges: [['upload', 'audio']], payload: '16 kHz mono WAV · 21 s',
      title: 'Audio is normalised',
      what: 'ffmpeg extracts the sound track and converts it to 16 kHz mono, cut into pieces small enough for the transcription service. Only the first 10 minutes are kept.',
      measured: '128 ms, inside the server', fails: 'Unreadable media stops here with a clear message; temporary audio files are always deleted.' },
    { node: 'transcribe', edges: [['audio', 'transcribe']], payload: '5 timed segments',
      title: 'Speech becomes text',
      what: 'Each piece goes to Whisper large-v3-turbo on Groq. Every sentence comes back with its start and end time, which later powers the clickable citations.',
      measured: '1.7 s for 21 s of audio', fails: 'If Groq is busy the next speech model in the chain takes over.' },
    { node: 'chunk', edges: [['transcribe', 'chunk']], payload: '1 chunk · 0:00–0:20',
      title: 'The transcript is cut into passages',
      what: 'Text is split into 500-character passages that overlap by 50, each keeping the time range of the speech it came from. Personal data such as emails and card numbers is masked first.',
      measured: 'Milliseconds', fails: 'Transcripts that are empty or far too long are rejected before any model is called.' },
    { node: 'notes', edges: [['chunk', 'notes']], payload: '“Project Review: March 14th Launch”',
      title: 'A model writes the notes',
      what: 'Three short calls: a title, a summary, and the findings (action items, decisions, open questions). Each answer must match a strict JSON shape or the next model is tried.',
      measured: 'Title 0.9 s · summary 0.6 s · findings 1.8 s · 741 tokens in, 219 out', fails: 'Free models rotate in a fixed order: Nemotron, gpt-oss on Groq, Gemini Flash, OpenRouter.' },
    { node: 'embed', edges: [['notes', 'embed']], payload: '768 numbers per passage',
      title: 'Passages are turned into vectors',
      what: 'An embedding model maps each passage to a list of numbers that captures its meaning, so “budget” can match “forty thousand dollars”.',
      measured: '0.7 s with gemini-embedding-001', fails: 'If Gemini is out of quota, Cloudflare Qwen embeds instead; the recording keeps that one model for every later question.' },
    { node: 'index', edges: [['embed', 'index']], payload: 'vectors + text + timestamps',
      title: 'Everything is stored for search',
      what: 'Vectors go into pgvector and the passages into an ordinary table, both tagged with this recording only, so one session can never see another’s data.',
      measured: 'Part of the 0.8 s indexing step', fails: 'If saving fails half-way, the partial index is removed; delete removes everything in one transaction.' },
    { node: 'ready', edges: [['index', 'ready']], payload: 'Done in 6.2 s',
      title: 'Your notes are ready',
      what: 'Title, summary, findings and the full transcript appear, and the recording can now answer questions.',
      measured: '6.2 s end to end for the 21 s clip', fails: 'Each step reports progress, so the screen always shows where the job is.' },
  ],
};

const chatSteps = (scenario) => {
  const answerable = scenario === 'answerable';
  const q = answerable ? 'What is the budget and how many engineers are on the team?' : 'Which cloud provider will host the mobile app?';
  return [
    { node: 'question', edges: [], payload: q, title: 'You ask a question',
      what: 'Up to 2048 bytes in any phrasing. Personal data is masked before it goes anywhere.',
      measured: '—', fails: 'Each question counts against today’s allowance (see Usage).' },
    { node: 'qembed', edges: [['question', 'qembed']], payload: '768 numbers', title: 'The question is embedded',
      what: 'The question is mapped into the same vector space the recording’s passages were stored in.',
      measured: '≈0.8 s (one embedding call)', fails: 'It always uses the recording’s own embedding model, never a mix.' },
    { node: 'dense', edges: [['qembed', 'dense'], ['question', 'bm25']], parallel: true, payload: '10 by meaning · 10 by keyword',
      title: 'Two searches run side by side',
      what: 'Dense search finds passages that mean the same thing; BM25 finds passages that share the exact words. Each returns its best 10.',
      measured: 'Dense 5 ms · BM25 1 ms (median)', fails: 'Passages are filtered to this recording before ranking.' },
    { node: 'rrf', edges: [['dense', 'rrf'], ['bm25', 'rrf']], parallel: true, payload: '12 merged candidates',
      title: 'The two lists are merged',
      what: 'Reciprocal Rank Fusion scores each passage by its rank in both lists, so something ranked well by either search survives.',
      measured: 'Under 1 ms', fails: '—' },
    { node: 'rerank', edges: [['rrf', 'rerank']], payload: 'top 4 passages',
      title: 'A small model re-reads them',
      what: 'TinyBERT, a cross-encoder running inside the server, reads the question and each candidate together and keeps the best four.',
      measured: '8 ms (median), no API call', fails: 'If the reranker cannot run, the question fails safely instead of answering from poor evidence.' },
    { node: 'llm', edges: [['rerank', 'llm']], payload: '{ answer, evidence: [quote…] }',
      title: 'A model drafts a cited answer',
      what: 'The four passages and the question go to one language model, which must reply in JSON with the answer and an exact quote for every claim.',
      measured: answerable ? '1.5–1.8 s · ≈375 tokens in, ≈110 out' : 'Same single call', fails: 'If a model’s output breaks the rules, the next free model is tried.' },
    { node: 'validate', edges: [['llm', 'validate']], payload: answerable ? 'quote verified' : 'no supporting quote',
      title: 'Every quote is checked',
      what: 'Each quote must be at least four words and appear word for word in the passage it cites. One bad quote rejects the whole answer.',
      measured: 'Milliseconds', fails: 'In the evaluation all 56 accepted citations were exact; 0 fabricated quotes got through.' },
    answerable
      ? { node: 'answer', edges: [['validate', 'answer']], payload: '“$40,000 and 12 engineers” · 0:00–0:20',
        title: 'You get a cited answer', what: 'The answer is shown with its quote and a timestamp, so you can check it against the recording.',
        measured: '≈2.1 s median for a whole question', fails: '—' }
      : { node: 'abstain', edges: [['validate', 'abstain']], payload: '“I could not find this information.”',
        title: 'Or it says it does not know', what: 'With no supporting quote the app refuses instead of guessing. In the evaluation it refused all 6 unanswerable questions and never refused an answerable one.',
        measured: 'Same speed as an answer', fails: '—' },
  ];
};

const chat = (scenario) => ({
  id: 'chat',
  label: 'Answering a question',
  nodes: [
    { id: 'question', label: 'Question', sub: 'in your words', x: 100, y: 110, mx: 180, my: 50 },
    { id: 'qembed', label: 'Embed', sub: 'question → numbers', x: 300, y: 60, mx: 90, my: 160 },
    { id: 'dense', label: 'Dense search', sub: 'pgvector · top 10', x: 500, y: 60, mx: 90, my: 270 },
    { id: 'bm25', label: 'Keyword search', sub: 'BM25 · top 10', x: 500, y: 180, mx: 270, my: 270 },
    { id: 'rrf', label: 'Merge', sub: 'RRF · 12', x: 700, y: 110, mx: 180, my: 380 },
    { id: 'rerank', label: 'Rerank', sub: 'TinyBERT · top 4', x: 900, y: 110, mx: 180, my: 490 },
    { id: 'llm', label: 'Draft answer', sub: 'JSON + quotes', x: 900, y: 310, mx: 180, my: 600 },
    { id: 'validate', label: 'Check quotes', sub: 'exact match', x: 700, y: 310, mx: 180, my: 710 },
    { id: 'answer', label: 'Cited answer', sub: 'quote + timestamp', x: 450, y: 290, mx: 90, my: 830, outcome: 'answerable' },
    { id: 'abstain', label: 'Abstain', sub: '“not in the recording”', x: 450, y: 400, mx: 270, my: 830, outcome: 'unanswerable' },
  ],
  edges: [['question', 'qembed'], ['qembed', 'dense'], ['question', 'bm25'], ['dense', 'rrf'], ['bm25', 'rrf'],
    ['rrf', 'rerank'], ['rerank', 'llm'], ['llm', 'validate'], ['validate', 'answer'], ['validate', 'abstain']],
  steps: chatSteps(scenario),
});

export function getFlow(id, scenario = 'answerable') {
  return id === 'chat' ? chat(scenario) : processing;
}

export const FLOW_TABS = [
  { id: 'processing', label: 'Processing a recording' },
  { id: 'chat', label: 'Answering a question' },
];

// Smooth curve between two node centres: horizontal S-curve, or a vertical one when nodes stack.
export function edgePath(a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (Math.abs(dx) >= Math.abs(dy)) {
    const c = dx / 2;
    return `M ${a.x} ${a.y} C ${a.x + c} ${a.y}, ${b.x - c} ${b.y}, ${b.x} ${b.y}`;
  }
  const c = dy / 2;
  return `M ${a.x} ${a.y} C ${a.x} ${a.y + c}, ${b.x} ${b.y - c}, ${b.x} ${b.y}`;
}
