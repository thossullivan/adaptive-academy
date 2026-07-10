import { describe, expect, it } from 'vitest';
import { changeSummary, gateBadge } from './programs';

describe('gateBadge', () => {
  it('maps gate/evidence verdicts to label + Badge-native tone', () => {
    expect(gateBadge('passed')).toEqual({ label: 'Verified', tone: 'success' });
    expect(gateBadge('overridden')).toEqual({ label: '⚠ Unverified (overridden)', tone: 'warn' });
    expect(gateBadge('open')).toEqual({ label: 'Open', tone: 'neutral' });
    expect(gateBadge('verified')).toEqual({ label: 'Verified', tone: 'success' });
    expect(gateBadge('stale')).toEqual({ label: 'Decayed', tone: 'warn' });
    expect(gateBadge('weak_artifact')).toEqual({ label: 'No artifact', tone: 'warn' });
    expect(gateBadge('never_probed_cold')).toEqual({ label: 'Never probed cold', tone: 'neutral' });
  });

  it('falls back to the raw verdict with a neutral tone', () => {
    expect(gateBadge('something_new')).toEqual({ label: 'something_new', tone: 'neutral' });
  });
});

describe('changeSummary', () => {
  it('renders each change kind as a human sentence', () => {
    expect(changeSummary({ kind: 'add_topic', payload: { milestone_id: 2, title: 'MoE routing' } }))
      .toBe('Add topic “MoE routing”');
    expect(changeSummary({ kind: 'add_milestone', payload: { title: 'Math refresh' } }))
      .toBe('Add milestone “Math refresh”');
    expect(changeSummary({ kind: 'revise_milestone', payload: { milestone_id: 2, title: 'New title' } }))
      .toBe('Revise milestone: New title');
    expect(changeSummary({ kind: 'revise_milestone', payload: { milestone_id: 2, success_criteria: 'bar' } }))
      .toBe('Revise milestone: new success criteria');
    expect(changeSummary({ kind: 'prune_topic', payload: { link_id: 5 } }))
      .toBe('Prune a planned topic');
    expect(changeSummary({ kind: 'prune_milestone', payload: { milestone_id: 3 } }))
      .toBe('Archive a milestone');
    expect(changeSummary({ kind: 'mystery', payload: {} })).toBe('mystery');
  });
});
