// Small text helpers for display.

/** Clip `text` to at most `max` characters on a word boundary, ending with an ellipsis.
 * Whitespace is collapsed. A single word longer than `max` is hard-cut. */
export function clipWords(text: string, max: number): { text: string; clipped: boolean } {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (normalized.length <= max) return { text: normalized, clipped: false };
  if (max <= 1) return { text: '…', clipped: true };
  const room = normalized.slice(0, max - 1); // leave space for the ellipsis
  const lastSpace = room.lastIndexOf(' ');
  // Cut at the last space unless that would drop most of the room (a long URL or identifier
  // early on): then hard-cut instead, so the clip still shows a useful amount.
  const cut = lastSpace >= room.length / 2 ? room.slice(0, lastSpace) : room;
  return { text: `${cut.replace(/[\s,;:.\-—–]+$/, '')}…`, clipped: true };
}

/** A phase's estimated time as written elsewhere ("12–15 hours"). The track generator gives
 *  it as free text: a bare number or range ("1.5", "10-12") gets its unit; text that already
 *  says what it is ("2 weeks") is left as it is. */
export function formatHours(est: string): string {
  const s = est.trim();
  const m = s.match(/^~?\s*(\d+(?:\.\d+)?)(?:\s*[-–]\s*\d+(?:\.\d+)?)?$/);
  if (!m) return s;
  const single = !/[-–]/.test(s) && Number(m[1]) === 1;
  return `${s} ${single ? 'hour' : 'hours'}`;
}

/** The next text for a live region showing `prev`. A repeat of the same message wouldn't
 *  change the DOM, so screen readers would stay silent; toggling a trailing no-break space
 *  (which they don't read) makes every call an announcement. */
export function announce(prev: string, text: string): string {
  return prev === text ? `${text} ` : text;
}
