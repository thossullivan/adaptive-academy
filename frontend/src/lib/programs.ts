// Tones are Badge-native (`$lib/ui` Badge `tone` prop values) so callers can pass
// them straight into `<Badge tone={...}>`.
export type BadgeTone = 'success' | 'warn' | 'neutral';

const BADGES: Record<string, { label: string; tone: BadgeTone }> = {
  passed: { label: 'Verified', tone: 'success' },
  verified: { label: 'Verified', tone: 'success' },
  overridden: { label: '⚠ Unverified (overridden)', tone: 'warn' },
  open: { label: 'Open', tone: 'neutral' },
  stale: { label: 'Decayed', tone: 'warn' },
  weak_artifact: { label: 'No artifact', tone: 'warn' },
  never_probed_cold: { label: 'Never probed cold', tone: 'neutral' }
};

export function gateBadge(verdict: string): { label: string; tone: BadgeTone } {
  return BADGES[verdict] ?? { label: verdict, tone: 'neutral' };
}

/** Human-readable one-line summary of a proposed map-revision change, keyed by `change.kind`. */
export function changeSummary(change: { kind: string; payload: Record<string, unknown> }): string {
  const p = change.payload;
  switch (change.kind) {
    case 'add_topic':
      return `Add topic “${p.title}”`;
    case 'add_milestone':
      return `Add milestone “${p.title}”`;
    case 'revise_milestone':
      return p.title ? `Revise milestone: ${p.title}` : 'Revise milestone: new success criteria';
    case 'prune_topic':
      return 'Prune a planned topic';
    case 'prune_milestone':
      return 'Archive a milestone';
    default:
      return change.kind;
  }
}
