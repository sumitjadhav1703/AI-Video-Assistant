// The backend returns markdown. This UI renders plain text, so strip the common
// inline markers (bold **/__, inline code, ATX headings) that would otherwise
// show literally. Only paired markers around text are removed, so identifiers
// such as __init__ or a lone backtick survive. A leading bullet/number marker is
// only treated as a marker when followed by whitespace, so "**Owner:**" is never
// mistaken for a bullet.
export function stripMd(str) {
  if (!str) return '';
  return str
    .replace(/(`+)([^\n]+?)\1(?!`)/g, '$2')
    .replace(/\*\*(?=\S)([^\n]*?\S)\*\*/g, '$1')
    // __word__ is far more often a Python dunder than bold, so keep bare identifiers.
    .replace(/(^|\W)__(?=\S)([^\n]*?\S)__(?!\w)/g, (match, before, text) => (/^\w+$/.test(text) ? match : before + text))
    .replace(/^#{1,6}\s+/gm, '')
    .trim();
}

const BULLET = /^\s*(?:[-•*]\s+|\d+[.)]\s+)/;

// Summary and findings -> clean, non-empty lines with markdown markers removed.
export function toLines(str) {
  if (!str) return [];
  return str
    .split('\n')
    .map((line) => stripMd(line.replace(BULLET, '')))
    .filter(Boolean);
}

// Transcript -> paragraphs split on blank lines, markdown stripped.
export function toParagraphs(str) {
  if (!str) return [];
  return str
    .split(/\n\s*\n/)
    .map((p) => stripMd(p))
    .filter(Boolean);
}

export function humanSize(bytes) {
  if (bytes == null) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(i > 0 && n < 10 ? 1 : 0)} ${units[i]}`;
}
