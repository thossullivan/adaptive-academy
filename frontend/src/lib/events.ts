// Agent-trace display helpers.

import type { EventOut } from './types';

export interface EventRow {
  kind: string;
  detail: string;
  count: number;
  created_at: string | null; // the latest occurrence in the run
}

/** Fold consecutive identical events (same kind + detail) into one row with a count and the
 * latest time. Order is kept, and a run is never merged across a different event. */
export function collapseEvents(events: EventOut[]): EventRow[] {
  const rows: EventRow[] = [];
  for (const e of events) {
    const last = rows[rows.length - 1];
    const at = e.created_at ?? null;
    if (last && last.kind === e.kind && last.detail === e.detail) {
      last.count += 1;
      if (at && (!last.created_at || Date.parse(utc(at)) >= Date.parse(utc(last.created_at)))) {
        last.created_at = at;
      }
    } else {
      rows.push({ kind: e.kind, detail: e.detail, count: 1, created_at: at });
    }
  }
  return rows;
}

// The API serializes SQLite's naive UTC datetimes without an offset; read them as UTC.
const utc = (iso: string) => (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);

/** Compact relative time ("5m ago"); empty for a missing or unparseable time. */
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '';
  const t = Date.parse(utc(iso));
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

// --- Plain-language activity -------------------------------------------------------------
// The dashboard shows what happened in words, not the raw trace. Only events that mean
// something to a learner become a sentence; bookkeeping (prompt tags, plan steps, guard
// checks) is left out here and stays on the Sources trace. A sentence only says what the
// event itself records: a number or a concept name appears only when the event carries it.

export type EventTone = 'good' | 'warn' | 'bad' | 'neutral';

export interface PlainEventRow {
  text: string;
  tone: EventTone;
  /** The raw events the sentence stands for ("kind detail", one per line), for hover text. */
  raw: string;
  count: number;
  created_at: string | null; // the latest occurrence
}

/** What a probe kind is called in a sentence ("Graded your recall answer …"). */
const PROBE_NOUN: Record<string, string> = {
  self_explanation: 'explanation',
  calibration: 'calibration probe',
  recall: 'recall answer',
  source_quiz: 'source quiz',
  roleplay: 'role-play',
  paper_probe: 'paper probe',
  artifact_review: 'artifact'
};

/** Prompts whose run is the only trace of a learner action (no other event marks it). The
 * prompt event says the agent ran, not how it went, so the sentence says no more than that. */
const PROMPT_SENTENCE: Record<string, string> = {
  'teach.grade': 'Ran the teach-back grader',
  'practice.pf_generate': 'Ran the practice problem writer',
  'practice.pf_consolidate': 'Ran the practice grader',
  'retention.propose': 'Ran the review card writer'
};

/** What an event prefix is called when it reports a failure. */
const AREA: Record<string, string> = {
  research: 'Research',
  program_research: 'Program research',
  program_revision: 'Map revision',
  curriculum: 'Track building',
  anchors: 'Quiz writing',
  memory: 'The memory index',
  vault: 'The vault',
  scout: 'Scout',
  story: 'The story',
  remediate: 'Catch-up planning'
};

const num = (detail: string, re: RegExp): number | null => {
  const m = detail.match(re);
  return m ? Number(m[1]) : null;
};
const pct = (score: number) => `${Math.round(score * 100)}%`;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
/** The pass line for a score (competence.HELD; not imported, to keep this module standalone). */
const PASS = 0.45;

/** Turn the raw trace (oldest first) into plain sentences, oldest first, with back-to-back
 * repeats folded into one row with a count. An assessment writes several events (probe,
 * graded, estimate, done); they fold into one sentence. `concepts` maps concept id to name. */
export function plainEvents(events: EventOut[], concepts: Record<number, string> = {}): PlainEventRow[] {
  const out: { text: string; tone: EventTone; raw: string; created_at: string | null }[] = [];
  const conceptName = (detail: string) => {
    const id = num(detail, /concept (\d+)/);
    return id != null ? concepts[id] : undefined;
  };
  let assess: { probe?: string; score?: number; raw: string[] } | null = null;

  for (const e of events) {
    const at = e.created_at ?? null;
    const raw = e.detail ? `${e.kind} ${e.detail}` : e.kind;
    const say = (text: string, tone: EventTone = 'neutral', rawText = raw) =>
      out.push({ text, tone, raw: rawText, created_at: at });

    switch (e.kind) {
      case 'assess:probe':
        assess = { probe: e.detail, raw: [raw] };
        continue;
      case 'assess:graded': {
        const score = num(e.detail, /score=([0-9.]+)/);
        assess = assess ?? { raw: [] };
        assess.raw.push(raw);
        if (score != null) assess.score = score;
        continue;
      }
      case 'assess:rules':
      case 'assess:mechanism':
      case 'assess:estimate':
        assess?.raw.push(raw);
        continue;
      case 'assess:done': {
        const name = conceptName(e.detail);
        const noun = (assess?.probe && PROBE_NOUN[assess.probe]) || 'answer';
        const what = `Graded your ${noun}${name ? ` on ${name}` : ''}`;
        const score = assess?.score;
        const lines = [...(assess?.raw ?? []), raw].join('\n');
        if (score != null) say(`${what}: ${pct(score)}`, score >= PASS ? 'good' : 'warn', lines);
        else say(what, 'neutral', lines);
        assess = null;
        continue;
      }
      case 'artifact:reviewed': {
        const score = num(e.detail, /score=([0-9.]+)/);
        if (score != null) say(`Reviewed a shipped artifact: ${pct(score)}`, score >= PASS ? 'good' : 'warn');
        else say('Reviewed a shipped artifact');
        continue;
      }
      case 'prompt': {
        const sentence = PROMPT_SENTENCE[e.detail.split('@')[0]];
        if (sentence) say(sentence);
        continue;
      }
      case 'research:done':
        say(e.detail ? `Research finished: ${e.detail}` : 'Research finished', 'good');
        continue;
      case 'curriculum:generated':
        say(e.detail ? `Drafted the track: ${e.detail}` : 'Drafted the track', 'good');
        continue;
      case 'anchors:done': {
        const n = num(e.detail, /(\d+)/);
        say(n != null ? `Wrote ${plural(n, 'source-grounded quiz', 'source-grounded quizzes')}` : 'Wrote source-grounded quizzes', 'good');
        continue;
      }
      case 'remediate:done': {
        const name = conceptName(e.detail);
        if (/nothing/.test(e.detail)) say('Checked for gaps: nothing to add');
        else say(name ? `Added a catch-up step for ${name}` : 'Added a catch-up step to the track', 'good');
        continue;
      }
      case 'story:done':
        say('Wrote your learning story', 'good');
        continue;
      case 'vault:export': {
        const n = num(e.detail, /(\d+) note/);
        const left = num(e.detail, /(\d+) left unchanged/);
        const text = n != null ? `Exported ${plural(n, 'note')} to your vault` : 'Exported notes to your vault';
        say(left ? `${text}, ${left} left unchanged` : text, left ? 'warn' : 'neutral');
        continue;
      }
      case 'vault:ingest': {
        const n = num(e.detail, /(\d+) note/);
        say(n != null ? `Brought in ${plural(n, 'note')} from your vault` : 'Brought in notes from your vault');
        continue;
      }
      case 'vault:sync_failed':
        say('Notebook sync to the vault failed', 'bad');
        continue;
      case 'attempt:accepted':
        say('The tutor accepted your attempt', 'good');
        continue;
      case 'attempt:rejected':
        say('Attempt not recorded: no working shown yet', 'warn');
        continue;
      case 'attempt:unverified':
        say('Attempt not recorded: the check was unavailable', 'warn');
        continue;
      case 'tool:reveal_solution:allowed':
        say('The tutor showed a worked solution', 'good');
        continue;
      case 'tool:reveal_solution:blocked':
        say('The tutor held back a solution until you try', 'warn');
        continue;
    }
    // Any other failure is worth knowing about, in words; everything else is bookkeeping.
    if (/error|failed/.test(e.kind)) say(`${AREA[e.kind.split(':')[0]] ?? 'An agent step'} hit a problem`, 'bad');
  }

  const rows: PlainEventRow[] = [];
  for (const r of out) {
    const last = rows[rows.length - 1];
    if (last && last.text === r.text) {
      last.count += 1;
      last.raw = `${last.raw}\n${r.raw}`;
      if (r.created_at && (!last.created_at || Date.parse(utc(r.created_at)) >= Date.parse(utc(last.created_at)))) {
        last.created_at = r.created_at;
      }
    } else {
      rows.push({ ...r, count: 1 });
    }
  }
  return rows;
}
