import { describe, expect, it } from 'vitest';
import { collapseEvents, timeAgo } from './events';

const ev = (kind: string, detail = '', created_at?: string) => ({ kind, detail, created_at });

describe('collapseEvents', () => {
  it('folds consecutive identical events into one row with a count and the latest time', () => {
    const out = collapseEvents([
      ev('vault:export', '12 notes', '2026-10-19T10:00:00'),
      ev('vault:export', '12 notes', '2026-10-19T10:01:00'),
      ev('vault:export', '12 notes', '2026-10-19T10:02:00'),
      ev('vault:export', '12 notes', '2026-10-19T10:03:00')
    ]);
    expect(out).toEqual([
      { kind: 'vault:export', detail: '12 notes', count: 4, created_at: '2026-10-19T10:03:00' }
    ]);
  });

  it('keeps order and does not merge across a different event or a different detail', () => {
    const out = collapseEvents([
      ev('vault:export', 'a'),
      ev('vault:export', 'a'),
      ev('research:done', '8'),
      ev('vault:export', 'a'),
      ev('vault:export', 'b')
    ]);
    expect(out.map((r) => [r.kind, r.detail, r.count])).toEqual([
      ['vault:export', 'a', 2],
      ['research:done', '8', 1],
      ['vault:export', 'a', 1],
      ['vault:export', 'b', 1]
    ]);
  });

  it('handles an empty list and events without a time', () => {
    expect(collapseEvents([])).toEqual([]);
    expect(collapseEvents([ev('x'), ev('x')])).toEqual([
      { kind: 'x', detail: '', count: 2, created_at: null }
    ]);
  });
});

describe('timeAgo', () => {
  const now = Date.parse('2026-10-19T12:00:00Z');
  it('reads naive API timestamps as UTC', () => {
    expect(timeAgo('2026-10-19T11:55:00', now)).toBe('5m ago');
    expect(timeAgo('2026-10-19T11:55:00Z', now)).toBe('5m ago');
  });
  it('scales from seconds to days', () => {
    expect(timeAgo('2026-10-19T11:59:40Z', now)).toBe('just now');
    expect(timeAgo('2026-10-19T09:00:00Z', now)).toBe('3h ago');
    expect(timeAgo('2026-10-16T12:00:00Z', now)).toBe('3d ago');
  });
  it('is empty for a missing or unparseable time', () => {
    expect(timeAgo(null, now)).toBe('');
    expect(timeAgo('nope', now)).toBe('');
  });
});
