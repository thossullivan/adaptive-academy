import { describe, expect, it } from 'vitest';
import { evidenceLabel, groupSuggestionsByKind, scoutCardTitle } from './api';
import type { TopicSuggestion } from './types';

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

describe('Scout suggestion UI helpers', () => {
  it('formats evidence labels', () => {
    expect(evidenceLabel({ kind: 'concept', id: 42 })).toBe('Concept #42');
    expect(evidenceLabel({ kind: 'neighbor', name: 'Sparse retrieval' })).toBe(
      'Neighbor: Sparse retrieval'
    );
    expect(evidenceLabel({ kind: 'chunk', ref: 'file:///vault/retrieval.md' })).toBe(
      'file:///vault/retrieval.md'
    );
    expect(evidenceLabel({ kind: 'paper_probe', id: 9 })).toBe('Paper probe #9');
  });

  it('groups suggestions by candidate kind', () => {
    expect(groupSuggestionsByKind(suggestions)).toEqual([
      { kind: 'frontier', suggestions: [suggestions[0]] },
      { kind: 'orphan_note', suggestions: [suggestions[1]] }
    ]);
  });

  it('collapses the Scout card at zero and labels non-empty cards', () => {
    expect(scoutCardTitle([])).toBeNull();
    expect(scoutCardTitle(suggestions)).toBe('Scout found 2');
  });
});
