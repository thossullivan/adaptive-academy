import { describe, expect, it } from 'vitest';
import { indexTicks } from './ticks';

describe('indexTicks (probe-count axis)', () => {
  it('is empty for no data and a single tick for one point', () => {
    expect(indexTicks(0)).toEqual([]);
    expect(indexTicks(1)).toEqual([0]);
  });

  it('labels every probe when there are few', () => {
    expect(indexTicks(2)).toEqual([0, 1]);
    expect(indexTicks(5)).toEqual([0, 1, 2, 3, 4]);
  });

  it('thins many probes to a whole-number step that always includes the first and last', () => {
    const t = indexTicks(22);
    expect(t.length).toBeLessThanOrEqual(8);
    expect(t[0]).toBe(0);
    expect(t[t.length - 1]).toBe(21);
    expect(t.every(Number.isInteger)).toBe(true);
  });

  it('never yields fractional or out-of-range ticks', () => {
    for (let n = 1; n <= 60; n++) {
      for (const max of [2, 4, 8]) {
        const t = indexTicks(n, max);
        expect(t.length).toBeLessThanOrEqual(Math.max(max, 1));
        expect(t.every((v) => Number.isInteger(v) && v >= 0 && v < n)).toBe(true);
        expect(new Set(t).size).toBe(t.length);
        expect(t[t.length - 1]).toBe(n - 1);
      }
    }
  });
});
