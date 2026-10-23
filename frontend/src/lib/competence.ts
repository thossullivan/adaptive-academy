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

export const HELD = 0.45; // medium+ counts as a passing signal
const CALIBRATED_GAP = 0.15;

/** What an artifact review did: it lights (or fails) the "shipped" signal rather than setting
 * the grade, so it reads against the same HELD threshold as conceptSignals' `shipped`. */
/** The score a program milestone's gate needs as artifact evidence (engine/gates.py
 *  ARTIFACT_THRESHOLD). Higher than HELD: shipping lights the signal, the gate asks for more. */
export const MILESTONE_ARTIFACT = 0.7;

/** How far the latest score moved the mean of all scores (0..1, oldest first), in percentage
 *  points to one decimal: mean(all) − mean(all but the latest). Null with fewer than two. */
export function meanShiftPoints(scores: number[]): number | null {
  if (scores.length < 2) return null;
  const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const shift = (mean(scores) - mean(scores.slice(0, -1))) * 100;
  const rounded = Math.round(shift * 10) / 10;
  return rounded === 0 ? 0 : rounded; // never -0
}

export function artifactOutcome(score: number): { shipped: boolean; meetsGate: boolean; label: string } {
  const shipped = score >= HELD;
  return { shipped, meetsGate: score >= MILESTONE_ARTIFACT, label: shipped ? 'shipped ✓' : 'shipped ✗' };
}

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

/** Verdict colours for marks (dots, stars, legend swatches). "verified" has its own teal
 *  (--verdict-verified), never the brand accent that primary buttons use. */
export const VERDICT_COLOR: Record<Verdict, string> = {
  solid: 'var(--success)',
  verified: 'var(--verdict-verified)',
  unverified: 'var(--muted)',
  shaky: 'var(--danger)',
  untested: 'var(--verdict-untested)'
};

/** The shape of each verdict's mark, so neighbours that are close in colour also differ in
 *  shape: "untested" (no evidence at all) is an empty ring, unlike the filled grey of
 *  "unverified"; "verified" is a diamond, unlike the round green of "solid". */
export type VerdictShape = 'dot' | 'ring' | 'diamond';
export const VERDICT_SHAPE: Record<Verdict, VerdictShape> = {
  solid: 'dot',
  verified: 'diamond',
  unverified: 'dot',
  shaky: 'dot',
  untested: 'ring'
};

/** Verdicts drawn hollow (see VERDICT_SHAPE). */
export const VERDICT_HOLLOW = Object.fromEntries(
  Object.entries(VERDICT_SHAPE).map(([v, shape]) => [v, shape === 'ring'])
) as Record<Verdict, boolean>;

/** Verdict colours for TEXT (the verdict word itself): every one at least 4.5:1. The word
 *  carries the meaning, so "untested" can use the faint text tone; VERDICT_COLOR's
 *  --verdict-untested is a ring stroke (3:1, a graphic). Every other verdict shares its mark
 *  colour, all of which pass 4.5:1 as text. */
export const VERDICT_TEXT_COLOR: Record<Verdict, string> = {
  ...VERDICT_COLOR,
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

// --- Why this verdict? -------------------------------------------------------
// A faithful, plain-language account of which signals drove a concept's verdict,
// mirroring conceptVerdict() exactly so the explanation can never drift from the rule.

export type SignalRole = 'support' | 'fault' | 'gap'; // corroborating / failing / missing

export interface SignalDetail {
  key: keyof ConceptSignals;
  glyph: string;
  label: string;
  role: SignalRole;
  note: string;
}

export interface VerdictRationale {
  verdict: Verdict;
  headline: string; // the one deciding sentence
  signals: SignalDetail[]; // all five, in fixed order
  nextStep: string | null; // what would move it up; null when already solid
}

const GLYPH: Record<keyof ConceptSignals, string> = {
  grade: '◆', decay: '↺', calibration: '◷', taught: '◳', shipped: '⚒'
};
const LABEL: Record<keyof ConceptSignals, string> = {
  grade: 'grade', decay: 'decay', calibration: 'calibration', taught: 'teaching', shipped: 'shipping'
};

function stateRole(state: SignalState): SignalRole {
  return state === 'lit' ? 'support' : state === 'bad' ? 'fault' : 'gap';
}

const NOTE: Record<keyof ConceptSignals, Record<string, string>> = {
  grade: {
    high: 'Graded high: the latest answer explained the mechanism well.',
    medium: 'Graded medium: partly there.',
    low: 'Graded low: the latest answer was weak.',
    unknown: 'Not graded yet.'
  },
  decay: {
    lit: 'Held cold on delayed recall.',
    bad: 'Slipped on delayed recall.',
    unlit: 'Not retested cold yet.'
  },
  calibration: {
    lit: 'Felt confidence matched reality.',
    bad: "Felt confidence didn't match reality.",
    unlit: 'Not calibrated yet.'
  },
  taught: {
    lit: 'Explained it to an audience.',
    bad: 'Teaching fell short.',
    unlit: 'Not taught yet.'
  },
  shipped: {
    lit: 'Shipped an artifact that meets its criteria.',
    bad: 'Shipped artifact fell short of its criteria.',
    unlit: 'Nothing shipped yet.'
  }
};

export function roleColor(role: SignalRole): string {
  return role === 'support' ? 'var(--success)' : role === 'fault' ? 'var(--danger)' : 'var(--faint)';
}

export function verdictRationale(s: ConceptSignals): VerdictRationale {
  const verdict = conceptVerdict(s);
  const gradeRole: SignalRole =
    s.grade === 'unknown' ? 'gap' : s.grade === 'low' ? 'fault' : 'support';

  const signals: SignalDetail[] = [
    { key: 'grade', glyph: GLYPH.grade, label: LABEL.grade, role: gradeRole,
      note: NOTE.grade[s.grade] ?? NOTE.grade.unknown },
    ...(['decay', 'calibration', 'taught', 'shipped'] as const).map((k) => ({
      key: k, glyph: GLYPH[k], label: LABEL[k], role: stateRole(s[k]),
      note: NOTE[k][s[k]]
    }))
  ];

  // Name the lit corroborators (everything but grade) and the active faults.
  const litLabels = (['decay', 'calibration', 'taught', 'shipped'] as const)
    .filter((k) => s[k] === 'lit').map((k) => LABEL[k]);
  const faults: string[] = [];
  if (s.grade === 'low') faults.push('the grade is low');
  if (s.decay === 'bad') faults.push('decay slipped');
  if (s.calibration === 'bad') faults.push('calibration was off');
  if (s.taught === 'bad') faults.push('teaching fell short');
  if (s.shipped === 'bad') faults.push('the shipped artifact fell short');

  let headline: string;
  let nextStep: string | null;
  switch (verdict) {
    case 'untested':
      headline = 'No evidence yet. This concept is untested.';
      nextStep = 'Get a first read: answer a probe or take an assessment.';
      break;
    case 'shaky':
      headline = `Shaky: ${faults.join('; ')}.`;
      nextStep = 'Shore it up: revisit the concept, then re-grade or retest it cold.';
      break;
    case 'solid':
      headline = `Solid: graded high and backed up by ${litLabels.join(' & ')}.`;
      nextStep = null;
      break;
    case 'verified':
      headline = `Verified: graded ${s.grade} and backed up by ${litLabels.join(' & ')}.`;
      nextStep = 'Push to solid: hold it cold on delayed recall, teach it, or ship it.';
      break;
    default: // unverified
      headline = `Unverified: graded ${s.grade}, but nothing backs it up yet.`;
      nextStep = 'Back it up: pass a delayed recall, teach it, or ship an artifact.';
  }
  return { verdict, headline, signals, nextStep };
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
