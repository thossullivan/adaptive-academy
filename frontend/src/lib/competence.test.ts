import { describe, it, expect } from 'vitest';
import { artifactOutcome, conceptSignals, conceptVerdict, verdictRationale } from './competence';
import type { Assessment } from './types';

// Minimal assessment factory (the signal logic only reads these fields).
function a(p: Partial<Assessment>): Assessment {
  return {
    id: 0, kind: 'self_explanation', prompt: '', response: '', verdict: '', score: 0,
    gaps: [], confidence_predicted: null, confidence_actual: null, delta: null,
    estimate_level: null, ...p
  } as Assessment;
}

describe('conceptSignals', () => {
  it('reads the latest grade and lights signals that pass', () => {
    // newest-first
    const list = [
      a({ id: 5, kind: 'self_explanation', estimate_level: 'high', score: 0.9 }),
      a({ id: 4, kind: 'recall', score: 0.6 }), // held
      a({ id: 3, kind: 'teach', score: 0.8 }), // taught
      a({ id: 2, kind: 'calibration', confidence_predicted: 0.7, confidence_actual: 0.72 }) // calibrated
    ];
    const s = conceptSignals(list);
    expect(s.grade).toBe('high');
    expect(s.decay).toBe('lit');
    expect(s.taught).toBe('lit');
    expect(s.calibration).toBe('lit');
  });

  it('marks a decayed recall and a miscalibration as bad', () => {
    const s = conceptSignals([
      a({ id: 3, kind: 'recall', score: 0.2, estimate_level: 'low' }),
      a({ id: 2, kind: 'calibration', confidence_predicted: 0.9, confidence_actual: 0.4 })
    ]);
    expect(s.decay).toBe('bad');
    expect(s.calibration).toBe('bad');
  });
});

describe('conceptVerdict (signals must agree)', () => {
  it('untested with no history', () => {
    expect(conceptVerdict(conceptSignals([]))).toBe('untested');
  });

  it('a grade alone is unverified', () => {
    expect(conceptVerdict(conceptSignals([a({ estimate_level: 'high', score: 0.9 })]))).toBe('unverified');
  });

  it('solid needs grade high AND a corroborating signal', () => {
    const v = conceptVerdict(conceptSignals([
      a({ id: 2, estimate_level: 'high', score: 0.9 }),
      a({ id: 1, kind: 'recall', score: 0.7 })
    ]));
    expect(v).toBe('solid');
  });

  it('a disagreeing signal pulls it to shaky even with a high grade', () => {
    const v = conceptVerdict(conceptSignals([
      a({ id: 2, estimate_level: 'high', score: 0.9 }),
      a({ id: 1, kind: 'recall', score: 0.2 }) // decayed
    ]));
    expect(v).toBe('shaky');
  });

  it('a shipped artifact corroborates a high grade into solid', () => {
    const v = conceptVerdict(conceptSignals([
      a({ id: 2, estimate_level: 'high', score: 0.9 }),
      a({ id: 1, kind: 'artifact_review', score: 0.8 })
    ]));
    expect(v).toBe('solid');
  });

  it('a shipped-but-failing artifact pulls to shaky', () => {
    const v = conceptVerdict(conceptSignals([
      a({ id: 2, estimate_level: 'high', score: 0.9 }),
      a({ id: 1, kind: 'artifact_review', score: 0.2 })
    ]));
    expect(v).toBe('shaky');
  });

  it('medium grade with corroboration is verified', () => {
    const v = conceptVerdict(conceptSignals([
      a({ id: 2, estimate_level: 'medium', score: 0.6 }),
      a({ id: 1, kind: 'teach', score: 0.7 })
    ]));
    expect(v).toBe('verified');
  });
});

describe('verdictRationale (why this verdict)', () => {
  const role = (r: ReturnType<typeof verdictRationale>, k: string) =>
    r.signals.find((d) => d.key === k)!.role;

  it('lists all five signals in a fixed order', () => {
    const r = verdictRationale(conceptSignals([]));
    expect(r.signals.map((d) => d.key)).toEqual([
      'grade', 'decay', 'calibration', 'taught', 'shipped'
    ]);
  });

  it('untested: no signals, points to a first read', () => {
    const r = verdictRationale(conceptSignals([]));
    expect(r.verdict).toBe('untested');
    expect(r.nextStep).toMatch(/assess|grade|first/i);
  });

  it('unverified: high grade, nothing corroborating — says so and suggests corroboration', () => {
    const r = verdictRationale(conceptSignals([a({ estimate_level: 'high', score: 0.9 })]));
    expect(r.verdict).toBe('unverified');
    expect(r.headline).toMatch(/nothing|corroborat/i);
    expect(r.nextStep).toMatch(/recall|teach|ship/i);
  });

  it('shaky from a low grade names the grade', () => {
    const r = verdictRationale(conceptSignals([a({ estimate_level: 'low', score: 0.2 })]));
    expect(r.verdict).toBe('shaky');
    expect(r.headline).toMatch(/low/i);
  });

  it('shaky from a failed signal names the failing signal and marks it a fault', () => {
    const r = verdictRationale(conceptSignals([
      a({ estimate_level: 'high', score: 0.9 }),
      a({ kind: 'recall', score: 0.2 }) // decayed
    ]));
    expect(r.verdict).toBe('shaky');
    expect(r.headline.toLowerCase()).toContain('decay');
    expect(role(r, 'decay')).toBe('fault');
  });

  it('solid names the corroborating signal and has no next step', () => {
    const r = verdictRationale(conceptSignals([
      a({ estimate_level: 'high', score: 0.9 }),
      a({ kind: 'teach', score: 0.8 })
    ]));
    expect(r.verdict).toBe('solid');
    expect(r.headline).toMatch(/teach/i);
    expect(r.nextStep).toBeNull();
  });

  it('classifies lit/unlit/bad as support/gap/fault', () => {
    const r = verdictRationale(conceptSignals([
      a({ estimate_level: 'high', score: 0.9 }),
      a({ kind: 'teach', score: 0.8 }), // lit -> support
      a({ kind: 'recall', score: 0.2 }) // bad -> fault
    ]));
    expect(role(r, 'taught')).toBe('support');
    expect(role(r, 'decay')).toBe('fault');
    expect(role(r, 'calibration')).toBe('gap'); // unlit
    expect(role(r, 'grade')).toBe('support'); // high
  });
});

describe('artifactOutcome', () => {
  it('reads an artifact review against the same HELD threshold as the shipped signal', () => {
    expect(artifactOutcome(0.72)).toEqual({ shipped: true, meetsGate: true, label: 'shipped ✓' });
    expect(artifactOutcome(0.55)).toEqual({ shipped: true, meetsGate: false, label: 'shipped ✓' });
    expect(artifactOutcome(0.45)).toEqual({ shipped: true, meetsGate: false, label: 'shipped ✓' });
    expect(artifactOutcome(0.44)).toEqual({ shipped: false, meetsGate: false, label: 'shipped ✗' });
    // stays in lockstep with conceptSignals
    expect(conceptSignals([a({ kind: 'artifact_review', score: 0.45 })]).shipped).toBe('lit');
    expect(conceptSignals([a({ kind: 'artifact_review', score: 0.44 })]).shipped).toBe('bad');
  });
});
