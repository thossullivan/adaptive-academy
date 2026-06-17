// Competence triangulation: a concept's standing is the AGREEMENT of hard-to-game signals,
// not a single grade. A high grade alone reads "unverified" until corroborated by durability
// (decay), self-knowledge (calibration), or teaching. Anti-Goodhart by construction.

import type { Assessment } from './types';
import { LEVEL_FILL } from './utils';
import { api } from './api';

export type SignalState = 'lit' | 'bad' | 'unlit';

export interface ConceptSignals {
  grade: string; // high | medium | low | unknown — latest mechanism-anchored estimate
  decay: SignalState; // held cold on delayed recall?
  calibration: SignalState; // felt confidence matched reality?
  taught: SignalState; // explained to an audience?
  shipped: SignalState; // built an artifact that meets its acceptance criteria?
}

export type Verdict = 'solid' | 'verified' | 'unverified' | 'shaky' | 'untested';

const HELD = 0.45; // medium+ counts as a passing signal
const CALIBRATED_GAP = 0.15;

/** Derive the four signals from a concept's assessment history (newest-first). */
export function conceptSignals(list: Assessment[]): ConceptSignals {
  const latest = list[0];
  const recall = list.find((a) => a.kind === 'recall');
  const calib = list.find((a) => a.confidence_predicted != null && a.confidence_actual != null);
  const teach = list.find((a) => a.kind === 'teach');
  const artifact = list.find((a) => a.kind === 'artifact_review');
  return {
    grade: latest?.estimate_level ?? 'unknown',
    decay: recall ? (recall.score >= HELD ? 'lit' : 'bad') : 'unlit',
    calibration: calib
      ? Math.abs((calib.confidence_predicted ?? 0) - (calib.confidence_actual ?? 0)) <= CALIBRATED_GAP
        ? 'lit'
        : 'bad'
      : 'unlit',
    taught: teach ? (teach.score >= HELD ? 'lit' : 'bad') : 'unlit',
    shipped: artifact ? (artifact.score >= HELD ? 'lit' : 'bad') : 'unlit'
  };
}

/** The triangulated verdict: signals must AGREE for "solid". */
export function conceptVerdict(s: ConceptSignals): Verdict {
  const gradeFill = LEVEL_FILL[s.grade] ?? 0;
  const states = [s.decay, s.calibration, s.taught, s.shipped];
  const anyDisagree = states.includes('bad'); // a signal actively failed (decayed / shipped-but-fails)
  const corroborated = states.includes('lit');
  const hasGrade = s.grade !== 'unknown';

  if (!hasGrade && !corroborated && !anyDisagree) return 'untested';
  if (s.grade === 'low' || anyDisagree) return 'shaky';
  if (s.grade === 'high' && (s.decay === 'lit' || s.taught === 'lit' || s.shipped === 'lit')) return 'solid';
  if (gradeFill >= 0.6 && corroborated) return 'verified';
  return 'unverified'; // a grade, but nothing yet corroborates it
}

export const VERDICT_COLOR: Record<Verdict, string> = {
  solid: 'var(--success)',
  verified: 'var(--accent)',
  unverified: 'var(--muted)',
  shaky: 'var(--danger)',
  untested: 'var(--faint)'
};

export const VERDICT_LABEL: Record<Verdict, string> = {
  solid: 'solid',
  verified: 'verified',
  unverified: 'unverified',
  shaky: 'shaky',
  untested: 'untested'
};

// Attention-ordering: shakiest/least-verified first.
export const VERDICT_RANK: Record<Verdict, number> = {
  shaky: 0,
  untested: 1,
  unverified: 2,
  verified: 3,
  solid: 4
};

export function sigColor(state: SignalState): string {
  return state === 'lit' ? 'var(--success)' : state === 'bad' ? 'var(--danger)' : 'var(--faint)';
}

/** Fetch + triangulate every concept at once (used by the Constellation). */
export async function conceptSignalsMap(
  conceptIds: number[]
): Promise<Record<number, { signals: ConceptSignals; verdict: Verdict }>> {
  const lists = await Promise.all(
    conceptIds.map((id) => api.listAssessments(id).catch(() => [] as Assessment[]))
  );
  const out: Record<number, { signals: ConceptSignals; verdict: Verdict }> = {};
  conceptIds.forEach((id, i) => {
    const signals = conceptSignals(lists[i]);
    out[id] = { signals, verdict: conceptVerdict(signals) };
  });
  return out;
}
