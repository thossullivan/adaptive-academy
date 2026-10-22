import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import type { QualityCalls, QualityReport, QualityWindow } from '$lib/types';
import QualityScorecard from './QualityScorecard.svelte';

const calls = (over: Partial<QualityCalls> = {}): QualityCalls => ({
  calls: 0,
  cost_usd: 0,
  unpriced_calls: 0,
  cost_per_call_usd: null,
  recorded_calls: 0,
  refusals: 0,
  empty_replies: 0,
  cut_offs: 0,
  invalid_outputs: 0,
  ...over
});

const empty: QualityWindow = {
  by_feature: [],
  by_model: [],
  grading: {
    calls: 0,
    cost_usd: 0,
    unpriced_calls: 0,
    graded_assessments: 0,
    cost_per_assessment_usd: null,
    first_attempts: 0,
    regenerations: 0,
    regenerations_per_grade: null,
    rejected: 0,
    rejected_failed_checks: 0,
    rejected_stopped: 0,
    rejected_share: null,
    top_failed_rules: []
  },
  guard: { checks: 0, blocked: 0, blocked_share: null, fallbacks: 0, unavailable: 0, unavailable_share: null }
};

const busy: QualityWindow = {
  by_feature: [
    { feature: 'assess', ...calls({ calls: 8, cost_usd: 0.4, cost_per_call_usd: 0.05, recorded_calls: 8, invalid_outputs: 2 }) },
    { feature: 'tutor', ...calls({ calls: 3, cost_usd: 0.03, cost_per_call_usd: 0.01 }) }
  ],
  by_model: [
    { model: 'claude-sonnet-4-6', experimental: false, ...calls({ calls: 10, cost_per_call_usd: 0.04, recorded_calls: 10, refusals: 1 }) },
    { model: 'deepseek/deepseek-v4', experimental: true, ...calls({ calls: 1, unpriced_calls: 1, recorded_calls: 1 }) }
  ],
  grading: {
    calls: 8,
    cost_usd: 0.4,
    unpriced_calls: 0,
    graded_assessments: 4,
    cost_per_assessment_usd: 0.1,
    first_attempts: 4,
    regenerations: 1,
    regenerations_per_grade: 0.25,
    rejected: 2,
    rejected_failed_checks: 1,
    rejected_stopped: 1,
    rejected_share: 0.25,
    top_failed_rules: [
      { rule_id: 'G13', count: 2 },
      { rule_id: 'G1', count: 1 }
    ]
  },
  guard: { checks: 5, blocked: 1, blocked_share: 0.2, fallbacks: 1, unavailable: 1, unavailable_share: 0.2 }
};

const report = (w: QualityWindow): QualityReport => ({
  grading_features: ['assess', 'decay', 'teach'],
  windows: { today: empty, last_7_days: empty, last_30_days: w, all_time: w }
});

describe('QualityScorecard', () => {
  it('shows the last 30 days by default with every number explained', () => {
    const { body } = render(QualityScorecard, { props: { report: report(busy) } });
    expect(body).toContain('Is each model doing its job?');
    expect(body).toMatch(/aria-pressed="true"[^>]*>Last 30 days/);
    // Cost per grade, and which features count.
    expect(body).toContain('$0.10');
    expect(body).toContain('Assess, Recall check, Teach');
    // Grading health.
    expect(body).toContain('0.25');
    expect(body).toContain('G13 · 2');
    expect(body).toContain('(25% of grades)');
    // Guard.
    expect(body).toContain('20%');
    expect(body).toMatch(/1 of 5 replies/);
    // Tables: per call, problems, and the experimental label.
    expect(body).toContain('2 wrong format (25%)');
    expect(body).toContain('not recorded'); // tutor: no outcome recorded
    expect(body).toContain('1 refused (10%)');
    expect(body).toContain('price unknown');
    expect(body).toContain('data-testid="experimental-label"');
    // Plain words: no em dashes or exclamation marks (Svelte's <!--[--> markers aside).
    expect(body.replace(/<!--.*?-->/g, '')).not.toMatch(/[—!]/);
  });

  it('says "no data yet" for an empty window', () => {
    const { body } = render(QualityScorecard, { props: { report: report(empty) } });
    expect(body).toContain('No data yet.');
    expect(body).toContain('No assessments were written in this window.');
    expect(body).toContain('No grades checked in this window yet.');
    expect(body).toContain('No tutor replies checked in this window yet.');
    expect(body).toContain('No model calls in this window yet.');
    expect(body).not.toContain('NaN');
  });

  it('explains a missing cost per grade when grading spend is unpriced', () => {
    const w = { ...empty, grading: { ...empty.grading, calls: 2, unpriced_calls: 2, graded_assessments: 1 } };
    const { body } = render(QualityScorecard, { props: { report: report(w) } });
    expect(body).toContain("The grading model's price is unknown.");
  });

  it('says the cost per grade leaves out grading calls with no price', () => {
    const grading = { ...busy.grading, calls: 9, unpriced_calls: 1 };
    const { body } = render(QualityScorecard, { props: { report: report({ ...busy, grading }) } });
    expect(body).toContain('$0.10');
    expect(body).toContain('Leaves out 1 grading call with no known price.');
    // All priced: no such note.
    const priced = render(QualityScorecard, { props: { report: report(busy) } }).body;
    expect(priced).not.toContain('no known price');
  });

  it('says grade format problems are in the grade checks, not under Problems', () => {
    const { body } = render(QualityScorecard, { props: { report: report(busy) } });
    expect(body).toContain(
      'A grade in the wrong format is counted under Grade checks above, not under Problems.'
    );
  });

  it('reports a load failure without breaking', () => {
    const { body } = render(QualityScorecard, { props: { report: null, error: 'boom' } });
    expect(body).toContain("Couldn't load the scorecard: boom");
  });
});
