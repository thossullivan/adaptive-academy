import { describe, it, expect } from 'vitest';
import { conceptSignals, conceptVerdict } from './competence';
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

  it('medium grade with corroboration is verified', () => {
    const v = conceptVerdict(conceptSignals([
      a({ id: 2, estimate_level: 'medium', score: 0.6 }),
      a({ id: 1, kind: 'teach', score: 0.7 })
    ]));
    expect(v).toBe('verified');
  });
});
