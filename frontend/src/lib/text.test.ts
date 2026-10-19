import { describe, expect, it } from 'vitest';
import { clipWords } from './text';

describe('clipWords', () => {
  it('leaves short text alone', () => {
    expect(clipWords('derive the gradient', 40)).toEqual({ text: 'derive the gradient', clipped: false });
  });

  it('cuts on a word boundary and ends with an ellipsis', () => {
    const out = clipWords('Derive the evidence lower bound by hand from Jensen inequality', 30);
    expect(out.clipped).toBe(true);
    expect(out.text).toBe('Derive the evidence lower…');
    expect(out.text.length).toBeLessThanOrEqual(30);
  });

  it('never ends on a dangling separator before the ellipsis', () => {
    expect(clipWords('alpha, beta, gamma delta', 14).text).toBe('alpha, beta…');
  });

  it('hard-cuts a single word longer than the limit', () => {
    const out = clipWords('Supercalifragilisticexpialidocious', 10);
    expect(out).toEqual({ text: 'Supercali…', clipped: true });
  });

  it('collapses whitespace', () => {
    expect(clipWords('  a\n  b  ', 10)).toEqual({ text: 'a b', clipped: false });
  });
});
