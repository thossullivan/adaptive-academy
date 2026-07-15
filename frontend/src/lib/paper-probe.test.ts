import { describe, expect, it } from 'vitest';
import { unanswered } from './paper-probe';

describe('unanswered', () => {
  it('counts questions with blank or missing answers', () => {
    const qs = [{ index: 0 }, { index: 1 }, { index: 2 }];
    expect(unanswered(qs, { 0: 'done', 1: '   ' })).toBe(2); // idx1 blank, idx2 missing
  });

  it('returns 0 when all answered', () => {
    const qs = [{ index: 0 }, { index: 1 }];
    expect(unanswered(qs, { 0: 'a', 1: 'b' })).toBe(0);
  });
});
