// Minimal, dependency-free, XSS-safe markdown for curriculum/LLM text.
// We escape ALL HTML first, then inject only our own tags — so raw HTML in the
// source can never execute. Supports **bold**, *em* / _em_, `code`, and (block) newlines
// and ``` fenced code blocks.

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

// A fenced block: ``` with an optional language word, the code, then a closing ```.
const FENCE = /```[^\n`]*\n([\s\S]*?)\n?```/g;

const lines = (s: string) => inlineMd(s).replace(/\n/g, '<br>');

/**
 * Inline markdown with line breaks, and ``` fenced code blocks as `<code class="md-pre">`
 * (a <code>, not a <pre>, so the result can sit inside a <p> or <span>; app.css shows it as a
 * block). Code is escaped and never formatted. An unclosed fence stays as text.
 */
export function blockMd(text: string): string {
  const src = text ?? '';
  let out = '';
  let last = 0;
  for (const m of src.matchAll(FENCE)) {
    const at = m.index ?? 0;
    // The block sits on its own lines: drop the line break on either side of it.
    out += lines(src.slice(last, at).replace(/\n$/, ''));
    out += `<code class="md-pre">${esc(m[1])}</code>`;
    last = at + m[0].length;
    if (src[last] === '\n') last++;
  }
  return out + lines(src.slice(last));
}
