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
