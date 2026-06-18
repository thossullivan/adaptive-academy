export type WindStateName = 'cruising' | 'steady' | 'fading' | 'becalmed';

export const STATE_LABEL: Record<string, string> = {
  cruising: 'Cruising',
  steady: 'Steady',
  fading: 'Fading',
  becalmed: 'Becalmed'
};

export const STATE_COLOR: Record<string, string> = {
  cruising: 'var(--success)',
  steady: 'var(--accent)',
  fading: 'var(--accent)',
  becalmed: 'var(--danger)'
};

// 0 = flat/still water (becalmed), 1 = lively seas (cruising). Drives sea-state animation strength.
const INTENSITY: Record<string, number> = { becalmed: 0, fading: 0.3, steady: 0.65, cruising: 1 };
export function seaIntensity(state: string): number {
  return INTENSITY[state] ?? 0;
}

// Adaptive tone: a short fade gets the playful voice; a heavy becalming gets the warm, gentle one.
export function comebackTone(state: string): 'playful' | 'warm' | null {
  if (state === 'fading') return 'playful';
  if (state === 'becalmed') return 'warm';
  return null;
}
