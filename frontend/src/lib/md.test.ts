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
