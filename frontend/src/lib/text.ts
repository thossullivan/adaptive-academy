// Small text helpers for display.

/** Clip `text` to at most `max` characters on a word boundary, ending with an ellipsis.
 * Whitespace is collapsed. A single word longer than `max` is hard-cut. */
export function clipWords(text: string, max: number): { text: string; clipped: boolean } {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (normalized.length <= max) return { text: normalized, clipped: false };
  if (max <= 1) return { text: '…', clipped: true };
  const room = normalized.slice(0, max - 1); // leave space for the ellipsis
  const lastSpace = room.lastIndexOf(' ');
  // Cut at the last space unless that would drop nearly everything (one giant word).
  const cut = lastSpace > 0 ? room.slice(0, lastSpace) : room;
  return { text: `${cut.replace(/[\s,;:.\-—–]+$/, '')}…`, clipped: true };
}
