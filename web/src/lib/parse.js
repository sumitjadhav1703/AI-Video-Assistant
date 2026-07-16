// The backend returns markdown. This UI renders plain text, so strip the common
// inline markers (bold **/__, inline code, ATX headings) that would otherwise
// show literally. A leading bullet/number marker is only treated as a marker
// when followed by whitespace, so "**Owner:**" is never mistaken for a bullet.
export function stripMd(str) {
  if (!str) return '';
  return str
    .replace(/`+/g, '')
    .replace(/\*\*/g, '')
    .replace(/__/g, '')
    .replace(/^#{1,6}\s+/gm, '')
    .trim();
}

const BULLET = /^\s*(?:[-•*]\s+|\d+[.)]\s+)/;

// Findings strings -> clean items, one per non-empty line, markdown stripped.
export function toItems(str) {
  if (!str) return [];
  return str
    .split('\n')
    .map((line) => stripMd(line.replace(BULLET, '')))
    .filter(Boolean);
}

// Summary -> one clean line per non-empty line (handles both prose paragraphs
// and inline bullet lists), markdown stripped.
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

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
