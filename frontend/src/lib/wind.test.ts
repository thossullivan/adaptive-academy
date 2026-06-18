import { describe, expect, it } from 'vitest';
import { comebackTone, seaIntensity } from './wind';

describe('wind helpers', () => {
  it('comebackTone: playful fade, warm becalming, launch when never sailed, null when healthy', () => {
    expect(comebackTone('fading')).toBe('playful');
    expect(comebackTone('becalmed')).toBe('warm');
    expect(comebackTone('unsailed')).toBe('launch');
    expect(comebackTone('steady')).toBeNull();
    expect(comebackTone('cruising')).toBeNull();
  });

  it('seaIntensity rises with momentum and is flat when becalmed or unsailed', () => {
    expect(seaIntensity('becalmed')).toBe(0);
    expect(seaIntensity('unsailed')).toBe(0);
    expect(seaIntensity('cruising')).toBeGreaterThan(seaIntensity('steady'));
    expect(seaIntensity('steady')).toBeGreaterThan(seaIntensity('fading'));
  });
});
