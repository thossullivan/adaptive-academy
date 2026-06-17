// Minimal, dependency-free, XSS-safe markdown for curriculum/LLM text.
// We escape ALL HTML first, then inject only our own tags — so raw HTML in the
// source can never execute. Supports **bold**, *em* / _em_, `code`, and (block) newlines.

const SENT = String.fromCharCode(0); // null byte — cannot occur in real text

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function inlineMd(text: string): string {
  let s = esc(text ?? '');

  // Protect `code` spans with sentinel placeholders so * inside them isn't italicised.
  const codes: string[] = [];
  s = s.replace(/`([^`]+)`/g, (_m, c) => {
    codes.push(c);
    return `${SENT}${codes.length - 1}${SENT}`;
  });

  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
  s = s.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, '$1<em>$2</em>');

  s = s.replace(new RegExp(`${SENT}(\\d+)${SENT}`, 'g'), (_m, i) => `<code>${codes[+i]}</code>`);
  return s;
}

export function blockMd(text: string): string {
  return inlineMd(text).replace(/\n/g, '<br>');
}
