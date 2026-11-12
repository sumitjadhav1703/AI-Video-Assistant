// Shared design tokens ported from the Minutes design.
export const SANS = "'Helvetica Neue',Helvetica,Arial,sans-serif";
export const MONO = "'Space Grotesk',sans-serif";
export const CODE = "'IBM Plex Mono',monospace";

export const INK = '#0e0e0d';       // background
export const CREAM = '#e8e5de';     // primary text
export const SUBTLE = '#a19e96';    // body copy
export const MUTE = '#6f6c65';      // labels
export const DIM = '#57544e';       // faint

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
