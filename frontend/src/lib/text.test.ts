import { describe, expect, it } from 'vitest';
import { announce, clipWords, formatHours } from './text';

describe('formatHours', () => {
  it('adds the unit to a bare number or range', () => {
    expect(formatHours('1.5')).toBe('1.5 hours');
    expect(formatHours('1')).toBe('1 hour');
    expect(formatHours(' 10-12 ')).toBe('10-12 hours');
    expect(formatHours('12–15')).toBe('12–15 hours');
    expect(formatHours('~3')).toBe('~3 hours');
  });

  it('leaves text that already has a unit alone', () => {
    expect(formatHours('12–15 hours')).toBe('12–15 hours');
    expect(formatHours('50–60 hours (~5–6 weeks)')).toBe('50–60 hours (~5–6 weeks)');
    expect(formatHours('2 weeks')).toBe('2 weeks');
  });
});

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

describe('clipWords with a long unbroken word early on', () => {
  it('hard-cuts instead of dropping almost everything', () => {
    const url = 'https://example.com/' + 'a'.repeat(200);
    const { text, clipped } = clipWords(`Read ${url}`, 120);
    expect(clipped).toBe(true);
    expect(text.length).toBe(120);
    expect(text.startsWith('Read https://example.com/aaa')).toBe(true);
  });
});

describe('announce', () => {
  it('changes the text on every call so a repeat is announced again', () => {
    const first = announce('', 'Card graded good.');
    const second = announce(first, 'Card graded good.');
    const third = announce(second, 'Card graded good.');
    expect(first).toBe('Card graded good.');
    expect(second).not.toBe(first);
    expect(second.trim()).toBe('Card graded good.');
    expect(third).toBe(first);
  });

  it('passes a new message through unchanged', () => {
    expect(announce('Challenge ready.', 'Card graded good.')).toBe('Card graded good.');
  });
});
