import { describe, it, expect } from 'vitest';
import { inlineMd, blockMd } from './md';

describe('inlineMd', () => {
  it('renders bold, em, and code', () => {
    expect(inlineMd('**Linear algebra** is *the* `softmax(x)`')).toBe(
      '<strong>Linear algebra</strong> is <em>the</em> <code>softmax(x)</code>'
    );
  });

  it('escapes HTML before injecting tags (XSS-safe)', () => {
    expect(inlineMd('<script>alert(1)</script>')).toBe(
      '&lt;script&gt;alert(1)&lt;/script&gt;'
    );
    expect(inlineMd('**<b>x</b>**')).toBe('<strong>&lt;b&gt;x&lt;/b&gt;</strong>');
  });

  it('does not italicise * inside code spans', () => {
    expect(inlineMd('`a*b*c`')).toBe('<code>a*b*c</code>');
  });

  it('leaves plain numbers with spaces untouched', () => {
    expect(inlineMd('build a GPT (Weeks 2 to 5)')).toBe('build a GPT (Weeks 2 to 5)');
  });

  it('handles underscores as emphasis', () => {
    expect(inlineMd('_emphasis_ here')).toBe('<em>emphasis</em> here');
  });
});

describe('blockMd', () => {
  it('converts newlines to <br>', () => {
    expect(blockMd('line one\nline two')).toBe('line one<br>line two');
  });
});

describe('blockMd fenced code', () => {
  it('renders a fenced block as escaped, unformatted code on its own lines', () => {
    const text = 'Mask first:\n```python\nscores = scores.masked_fill(mask == 0, float("-inf"))\nw = softmax(scores * 2)\n```\nThen softmax.';
    expect(blockMd(text)).toBe(
      'Mask first:<code class="md-pre">scores = scores.masked_fill(mask == 0, float("-inf"))\nw = softmax(scores * 2)</code>Then softmax.'
    );
  });

  it('never lets HTML in a fenced block through', () => {
    expect(blockMd('```\n<img src=x onerror=alert(1)>\n```')).toBe(
      '<code class="md-pre">&lt;img src=x onerror=alert(1)&gt;</code>'
    );
  });

  it('leaves an unclosed fence as text and keeps inline code working beside blocks', () => {
    expect(blockMd('```\nnot closed')).toBe('```<br>not closed');
    expect(blockMd('use `-inf`\n```\nx\n```')).toBe('use <code>-inf</code><code class="md-pre">x</code>');
  });
});
