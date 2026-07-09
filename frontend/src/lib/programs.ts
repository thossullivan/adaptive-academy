export type BadgeTone = 'ok' | 'warn' | 'muted';

const BADGES: Record<string, { label: string; tone: BadgeTone }> = {
  passed: { label: 'Verified', tone: 'ok' },
  verified: { label: 'Verified', tone: 'ok' },
  overridden: { label: '⚠ Unverified (overridden)', tone: 'warn' },
  open: { label: 'Open', tone: 'muted' },
  stale: { label: 'Decayed', tone: 'warn' },
  weak_artifact: { label: 'No artifact', tone: 'warn' },
  never_probed_cold: { label: 'Never probed cold', tone: 'muted' }
};

export function gateBadge(verdict: string): { label: string; tone: BadgeTone } {
  return BADGES[verdict] ?? { label: verdict, tone: 'muted' };
}
