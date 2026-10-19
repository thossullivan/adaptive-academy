// Agent-trace display helpers.

import type { EventOut } from './types';

export interface EventRow {
  kind: string;
  detail: string;
  count: number;
  created_at: string | null; // the latest occurrence in the run
}

/** Fold consecutive identical events (same kind + detail) into one row with a count and the
 * latest time. Order is kept, and a run is never merged across a different event. */
export function collapseEvents(events: EventOut[]): EventRow[] {
  const rows: EventRow[] = [];
  for (const e of events) {
    const last = rows[rows.length - 1];
    const at = e.created_at ?? null;
    if (last && last.kind === e.kind && last.detail === e.detail) {
      last.count += 1;
      if (at && (!last.created_at || Date.parse(utc(at)) >= Date.parse(utc(last.created_at)))) {
        last.created_at = at;
      }
    } else {
      rows.push({ kind: e.kind, detail: e.detail, count: 1, created_at: at });
    }
  }
  return rows;
}

// The API serializes SQLite's naive UTC datetimes without an offset; read them as UTC.
const utc = (iso: string) => (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);

/** Compact relative time ("5m ago"); empty for a missing or unparseable time. */
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '';
  const t = Date.parse(utc(iso));
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}
