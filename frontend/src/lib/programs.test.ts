import { describe, expect, it } from 'vitest';
import { gateBadge } from './programs';

describe('gateBadge', () => {
  it('maps gate/evidence verdicts to label + Badge-native tone', () => {
    expect(gateBadge('passed')).toEqual({ label: 'Verified', tone: 'success' });
    expect(gateBadge('overridden')).toEqual({ label: '⚠ Unverified (overridden)', tone: 'warn' });
    expect(gateBadge('open')).toEqual({ label: 'Open', tone: 'neutral' });
    expect(gateBadge('verified')).toEqual({ label: 'Verified', tone: 'success' });
    expect(gateBadge('stale')).toEqual({ label: 'Decayed', tone: 'warn' });
    expect(gateBadge('weak_artifact')).toEqual({ label: 'No artifact', tone: 'warn' });
    expect(gateBadge('never_probed_cold')).toEqual({ label: 'Never probed cold', tone: 'neutral' });
  });

  it('falls back to the raw verdict with a neutral tone', () => {
    expect(gateBadge('something_new')).toEqual({ label: 'something_new', tone: 'neutral' });
  });
});
