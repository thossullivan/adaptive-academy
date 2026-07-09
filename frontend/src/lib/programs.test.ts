import { describe, expect, it } from 'vitest';
import { gateBadge } from './programs';

describe('gateBadge', () => {
  it('maps gate/evidence verdicts to label + tone', () => {
    expect(gateBadge('passed')).toEqual({ label: 'Verified', tone: 'ok' });
    expect(gateBadge('overridden')).toEqual({ label: '⚠ Unverified (overridden)', tone: 'warn' });
    expect(gateBadge('open')).toEqual({ label: 'Open', tone: 'muted' });
    expect(gateBadge('verified')).toEqual({ label: 'Verified', tone: 'ok' });
    expect(gateBadge('stale')).toEqual({ label: 'Decayed', tone: 'warn' });
    expect(gateBadge('weak_artifact')).toEqual({ label: 'No artifact', tone: 'warn' });
    expect(gateBadge('never_probed_cold')).toEqual({ label: 'Never probed cold', tone: 'muted' });
  });
});
