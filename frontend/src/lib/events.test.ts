import { describe, expect, it } from 'vitest';
import { collapseEvents, plainEvents, timeAgo } from './events';

const ev = (kind: string, detail = '', created_at?: string) => ({ kind, detail, created_at });

describe('collapseEvents', () => {
  it('folds consecutive identical events into one row with a count and the latest time', () => {
    const out = collapseEvents([
      ev('vault:export', '12 notes', '2026-10-19T10:00:00'),
      ev('vault:export', '12 notes', '2026-10-19T10:01:00'),
      ev('vault:export', '12 notes', '2026-10-19T10:02:00'),
      ev('vault:export', '12 notes', '2026-10-19T10:03:00')
    ]);
    expect(out).toEqual([
      { kind: 'vault:export', detail: '12 notes', count: 4, created_at: '2026-10-19T10:03:00' }
    ]);
  });

  it('keeps order and does not merge across a different event or a different detail', () => {
    const out = collapseEvents([
      ev('vault:export', 'a'),
      ev('vault:export', 'a'),
      ev('research:done', '8'),
      ev('vault:export', 'a'),
      ev('vault:export', 'b')
    ]);
    expect(out.map((r) => [r.kind, r.detail, r.count])).toEqual([
      ['vault:export', 'a', 2],
      ['research:done', '8', 1],
      ['vault:export', 'a', 1],
      ['vault:export', 'b', 1]
    ]);
  });

  it('handles an empty list and events without a time', () => {
    expect(collapseEvents([])).toEqual([]);
    expect(collapseEvents([ev('x'), ev('x')])).toEqual([
      { kind: 'x', detail: '', count: 2, created_at: null }
    ]);
  });
});

describe('timeAgo', () => {
  const now = Date.parse('2026-10-19T12:00:00Z');
  it('reads naive API timestamps as UTC', () => {
    expect(timeAgo('2026-10-19T11:55:00', now)).toBe('5m ago');
    expect(timeAgo('2026-10-19T11:55:00Z', now)).toBe('5m ago');
  });
  it('scales from seconds to days', () => {
    expect(timeAgo('2026-10-19T11:59:40Z', now)).toBe('just now');
    expect(timeAgo('2026-10-19T09:00:00Z', now)).toBe('3h ago');
    expect(timeAgo('2026-10-16T12:00:00Z', now)).toBe('3d ago');
  });
  it('is empty for a missing or unparseable time', () => {
    expect(timeAgo(null, now)).toBe('');
    expect(timeAgo('nope', now)).toBe('');
  });
});

describe('plainEvents', () => {
  const texts = (events: ReturnType<typeof ev>[], concepts: Record<number, string> = {}) =>
    plainEvents(events, concepts).map((r) => r.text);

  it('folds one assessment (probe, prompt, graded, estimate, done) into one sentence with the concept name', () => {
    const rows = plainEvents(
      [
        ev('assess:probe', 'recall', '2026-10-19T10:00:00'),
        ev('prompt', 'assess.grade@v7:standard', '2026-10-19T10:00:00'),
        ev('assess:graded', 'score=0.79', '2026-10-19T10:00:00'),
        ev('assess:estimate', 'level=high', '2026-10-19T10:00:00'),
        ev('assess:done', 'concept 3', '2026-10-19T10:00:00')
      ],
      { 3: 'KV Cache' }
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].text).toBe('Graded your recall answer on KV Cache: 79%');
    expect(rows[0].tone).toBe('good');
    // The raw events stay with the sentence (hover text), so nothing is hidden for good.
    expect(rows[0].raw).toContain('assess:done concept 3');
    expect(rows[0].raw).toContain('assess:graded score=0.79');
  });

  it('never invents a concept name or a score the events do not carry', () => {
    expect(texts([ev('assess:done', 'concept 99')])).toEqual(['Graded your answer']);
    expect(texts([ev('assess:probe', 'self_explanation'), ev('assess:done', 'concept 1')], { 1: 'Attention' })).toEqual([
      'Graded your explanation on Attention'
    ]);
    expect(texts([ev('remediate:done', 'concept 4')])).toEqual(['Added a catch-up step to the track']);
    expect(texts([ev('anchors:done', '')])).toEqual(['Wrote source-grounded quizzes']);
  });

  it('marks a low score as a warning, not a success', () => {
    const [row] = plainEvents([ev('assess:graded', 'score=0.3'), ev('assess:done', 'concept 1')]);
    expect(row.text).toBe('Graded your answer: 30%');
    expect(row.tone).toBe('warn');
  });

  it('leaves out bookkeeping: prompt tags, plan steps, guard checks, llm calls', () => {
    expect(
      texts([
        ev('prompt', 'assess.grade@v7:standard'),
        ev('prompt', 'tutor.base@v5'),
        ev('research:plan', '4 briefs'),
        ev('research:subagent', 'math: 3 sources'),
        ev('curriculum:plan', '12 concepts'),
        ev('curriculum:done', 'track 1'),
        ev('guard:attempt_checked', 'source=model attempted=true'),
        ev('llm_call', 'step=1'),
        ev('levels', 'assistance=2 challenge=3'),
        ev('graph:edges', '9 edges, 0 unresolved')
      ])
    ).toEqual([]);
  });

  it('says what learner-facing events did, in plain words', () => {
    expect(
      texts([
        ev('research:done', '12 sources proposed'),
        ev('curriculum:generated', '4 phases'),
        ev('anchors:done', '3 anchor(s) created'),
        ev('remediate:done', 'concept 2'),
        ev('prompt', 'teach.grade@v2'),
        ev('prompt', 'practice.pf_generate@v3'),
        ev('artifact:reviewed', 'score=0.8, 2 concept(s)'),
        ev('vault:export', '12 note(s) to vault, 1 left unchanged'),
        ev('vault:ingest', '1 note(s) from vault'),
        ev('story:done', 'A month of attention'),
        ev('attempt:accepted', 'recorded: the worked solution can now be revealed'),
        ev('tool:reveal_solution:allowed')
      ], { 2: 'Causal Self-Attention' })
    ).toEqual([
      'Research finished: 12 sources proposed',
      'Drafted the track: 4 phases',
      'Wrote 3 source-grounded quizzes',
      'Added a catch-up step for Causal Self-Attention',
      'Ran the teach-back grader',
      'Ran the practice problem writer',
      'Reviewed a shipped artifact: 80%',
      'Exported 12 notes to your vault, 1 left unchanged',
      'Brought in 1 note from your vault',
      'Wrote your learning story',
      'The tutor accepted your attempt',
      'The tutor showed a worked solution'
    ]);
  });

  it('reports failures in words, with the area they came from', () => {
    const rows = plainEvents([ev('research:subagent_error', 'timeout'), ev('vault:sync_failed', 'x'), ev('weird:error')]);
    expect(rows.map((r) => [r.text, r.tone])).toEqual([
      ['Research hit a problem', 'bad'],
      ['Notebook sync to the vault failed', 'bad'],
      ['An agent step hit a problem', 'bad']
    ]);
  });

  it('folds back-to-back repeats of a sentence into one row with a count and the latest time', () => {
    const rows = plainEvents([
      ev('vault:export', '12 note(s) to vault', '2026-10-19T10:00:00'),
      ev('vault:export', '12 note(s) to vault', '2026-10-19T10:05:00'),
      ev('research:done', '8 sources proposed', '2026-10-19T10:06:00'),
      ev('vault:export', '12 note(s) to vault', '2026-10-19T10:07:00')
    ]);
    expect(rows.map((r) => [r.text, r.count, r.created_at])).toEqual([
      ['Exported 12 notes to your vault', 2, '2026-10-19T10:05:00'],
      ['Research finished: 8 sources proposed', 1, '2026-10-19T10:06:00'],
      ['Exported 12 notes to your vault', 1, '2026-10-19T10:07:00']
    ]);
  });
});
