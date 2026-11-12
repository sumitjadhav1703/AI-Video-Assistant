// Shared design tokens ported from the Minutes design.
export const SANS = "'Helvetica Neue',Helvetica,Arial,sans-serif";
export const MONO = "'Space Grotesk',sans-serif";

export const INK = '#0e0e0d';       // background
export const CREAM = '#e8e5de';     // primary text
export const SUBTLE = '#a19e96';    // body copy
export const MUTE = '#8a877f';      // labels, 5.4:1 on INK
export const DIM = '#807d75';       // faint, 4.7:1 on INK (WCAG AA)

// The six pipeline steps, in backend order. Index maps 1:1 to the stage list.
export const STEP_ORDER = ['audio', 'transcript', 'title', 'summary', 'extract', 'rag'];
export const STAGE_NAMES = [
  'Audio processing',
  'Transcription',
  'Title generation',
  'Summarisation',
  'Extraction',
  'RAG engine',
];
