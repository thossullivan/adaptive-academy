// Minimal, dependency-free, XSS-safe markdown for curriculum/LLM text.
// We escape ALL HTML first, then inject only our own tags, so raw HTML in the source can
// never execute. Supports **bold**, *em* / _em_, `code`, line breaks and ``` fenced code.
//
// Emphasis is strict, so maths and code read as typed: a marker needs a non-space character
// just inside it, and no letter or digit just outside it. `x**2 + y**2`, `2*3*4`, `3 * x * y`
// and snake_case stay literal; *why*, **bold** and _this_ still format.

const SENT = String.fromCharCode(0); // the code-span placeholder; stripped from the input first

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** The input without NUL characters, which would collide with the code-span placeholder. */
function clean(text: string | null | undefined): string {
  return (text ?? '').split(SENT).join('');
}

const STRONG = /(^|[^\w*])\*\*(?=[^\s*])([^*]*?[^\s*])\*\*(?![\w*])/g;
const EM_STAR = /(^|[^\w*])\*(?=[^\s*])([^*\n]*?[^\s*])\*(?![\w*])/g;
const EM_UNDERSCORE = /(^|[^\w_])_(?=[^\s_])([^_\n]*?[^\s_])_(?![\w_])/g;

export function inlineMd(text: string): string {
  let s = esc(clean(text));

  // Protect `code` spans with placeholders so * inside them isn't formatted.
  const codes: string[] = [];
  s = s.replace(/`([^`]+)`/g, (_m, c) => {
    codes.push(c);
    return `${SENT}${codes.length - 1}${SENT}`;
  });

  s = s.replace(STRONG, '$1<strong>$2</strong>');
  s = s.replace(EM_STAR, '$1<em>$2</em>');
  s = s.replace(EM_UNDERSCORE, '$1<em>$2</em>');

  s = s.replace(new RegExp(`${SENT}(\\d+)${SENT}`, 'g'), (_m, i) => `<code>${codes[+i]}</code>`);
  return s;
}

// A fenced block: ``` with an optional language word, the code, then a closing ```.
const FENCE = /```[^\n`]*\n([\s\S]*?)\n?```/g;

/** Inline markdown per stretch of text, ``` fenced blocks as `<code class="md-pre">`. */
function withFences(text: string, lines: (s: string) => string): string {
  const src = clean(text);
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

/**
 * Inline markdown with line breaks as <br>, and ``` fenced code blocks as
 * `<code class="md-pre">` (a <code>, not a <pre>, so the result can sit inside a <p> or
 * <span>; app.css shows it as a block). Code is escaped and never formatted. An unclosed
 * fence stays as text.
 */
export function blockMd(text: string): string {
  return withFences(text, (s) => inlineMd(s).replace(/\n/g, '<br>'));
}

/**
 * Like blockMd, but line breaks and indentation stay as typed: show it in a
 * `white-space: pre-wrap` element (Markdown.svelte `pre`). For tutor replies.
 */
export function preMd(text: string): string {
  return withFences(text, inlineMd);
}
