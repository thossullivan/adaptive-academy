import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import type { TopicSuggestion } from '$lib/types';
import ScoutCard from './ScoutCard.svelte';

const suggestions: TopicSuggestion[] = [
  {
    id: 1,
    program_id: 7,
    title: 'Sparse retrieval',
    rationale: 'A repeated frontier signal.',
    candidate_kind: 'frontier',
    evidence: [{ kind: 'concept', id: 42 }, { kind: 'neighbor', name: 'Sparse retrieval' }],
    score: 0.9,
    status: 'proposed',
    created_at: '2026-08-25T12:00:00Z',
    decided_at: null
  },
  {
    id: 2,
    program_id: 7,
    title: 'Retrieval notebook',
    rationale: 'An unlinked note supports this topic.',
    candidate_kind: 'orphan_note',
    evidence: [{ kind: 'chunk', ref: 'file:///vault/retrieval.md' }],
    score: 0.7,
    status: 'proposed',
    created_at: '2026-08-25T12:00:00Z',
    decided_at: null
  }
];
const noop = () => {};

describe('ScoutCard', () => {
  it('renders grouped suggestions with rationale, evidence, target, and actions', () => {
    const { body } = render(ScoutCard, {
      props: {
        suggestions,
        title: 'Scout found 2',
        targetLabel: 'Milestone 1',
        onaccept: noop,
        ondismiss: noop
      }
    });
    expect(body).toContain('Scout found 2');
    expect(body).toContain('frontier');
    expect(body).toContain('orphan note');
    expect(body).toContain('Sparse retrieval');
    expect(body).toContain('A repeated frontier signal.');
    expect(body).toContain('Evidence (2)');
    expect(body).toContain('Concept #42');
    expect(body).toContain('Accept → Milestone 1');
    expect(body).toContain('Accept');
    expect(body).toContain('Dismiss');
    expect(body).not.toContain('90%');
  });

  it('shows the score when asked and the empty text when there is nothing', () => {
    const scored = render(ScoutCard, {
      props: { suggestions, title: 'Scout', showScore: true, onaccept: noop, ondismiss: noop }
    });
    expect(scored.body).toContain('90%');

    const empty = render(ScoutCard, {
      props: {
        suggestions: [],
        title: 'Scout',
        emptyText: 'No proposed suggestions.',
        error: 'Something failed.',
        onaccept: noop,
        ondismiss: noop
      }
    });
    expect(empty.body).toContain('No proposed suggestions.');
    expect(empty.body).toContain('Something failed.');
    expect(empty.body).not.toContain('>Accept<');
  });
});
