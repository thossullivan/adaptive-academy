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

/** The input without NUL characters, which would collide with the code-span placeholder,
 *  and with Windows (\r\n) and old Mac (\r) line endings as plain \n. */
function clean(text: string | null | undefined): string {
  return (text ?? '').split(SENT).join('').replace(/\r\n?/g, '\n');
}

const STRONG_EM = /(^|[^\w*])\*\*\*(?=[^\s*])([^*]*?[^\s*])\*\*\*(?![\w*])/g;
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

  s = s.replace(STRONG_EM, '$1<strong><em>$2</em></strong>');
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

// A list line: up to three spaces, then "- " or "* " (bulleted) or "N. " (numbered, N of one
// to three digits, so "1905. That year" stays a sentence), then text. "-5 is negative" and
// "1.5 is a ratio" have no space after the marker: not lists.
const BULLET = /^ {0,3}[-*] +(?=\S)(.*)$/;
const NUMBERED = /^ {0,3}(\d{1,3})\. +(?=\S)(.*)$/;
// A thematic break ("* * *", "- - -", "___"): only markers and spaces. Never a list item.
const RULE = /^[ *_-]+$/;
// A ``` line that withFences left alone has no closing fence. As in CommonMark, it runs to
// the end of the text, so nothing after it becomes a list.
const OPEN_FENCE = /^ {0,3}```/;

/** Runs of list lines as <ul>/<ol>, everything else as inline markdown with its line
 *  breaks kept. Each item goes through inlineMd (escaped, then formatted); the markers and
 *  the line break on either side of a list are dropped, as for a fenced block, and so is one
 *  blank line on either side (the list's margin). No whitespace sits between the tags, since
 *  the result is shown pre-wrap. As in CommonMark, a list marker wins over a code span that
 *  crosses lines: the line is a list item, and the span's backticks stay literal. */
function withLists(src: string): string {
  // Consecutive lines of one kind (text, ul or ol) make one block.
  type Block = { tag: 'text' | 'ul' | 'ol'; start: number; lines: string[] };
  const blocks: Block[] = [];
  let fenced = false;
  for (const line of src.split('\n')) {
    const last = blocks.at(-1);
    if (OPEN_FENCE.test(line)) fenced = true;
    const listy = !fenced && !RULE.test(line);
    const bullet = listy ? line.match(BULLET) : null;
    const numbered = listy && !bullet ? line.match(NUMBERED) : null;
    const tag = bullet ? 'ul' : numbered ? 'ol' : 'text';
    const content = bullet ? bullet[1] : numbered ? numbered[2] : line;
    if (last?.tag === tag) last.lines.push(content);
    else blocks.push({ tag, start: numbered ? Number(numbered[1]) : 1, lines: [content] });
  }
  return blocks
    .map(({ tag, start, lines }, i) => {
      if (tag === 'text') {
        // One blank line on either side of a list is the list's margin's job.
        const from = i > 0 && lines[0] === '' ? 1 : 0;
        const to = i < blocks.length - 1 && lines.length > from && lines.at(-1) === '' ? -1 : undefined;
        return inlineMd(lines.slice(from, to).join('\n'));
      }
      const items = lines.map((item) => `<li>${inlineMd(item)}</li>`).join('');
      const from = tag === 'ol' && start !== 1 ? ` start="${start}"` : '';
      return `<${tag} class="md-list"${from}>${items}</${tag}>`;
    })
    .join('');
}

/**
 * Like blockMd, but line breaks and indentation stay as typed: show it in a
 * `white-space: pre-wrap` element (Markdown.svelte `pre`). For tutor replies. Lines that
 * start with "- " or "* " become a <ul>, lines that start with "1. " an <ol>. An unclosed
 * fence stays as text, as in blockMd, and nothing after it becomes a list.
 */
export function preMd(text: string): string {
  return withFences(text, withLists);
}
