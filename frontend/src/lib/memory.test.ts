import { describe, expect, it } from 'vitest';
import type { MemoryHit } from './types';
import { groupByKind, trimSnippet } from './memory';

function hit(kind: string): MemoryHit {
  return {
    chunk_id: 1,
    kind,
    heading: `${kind} heading`,
    snippet: `${kind} snippet`,
    score: 1,
    source_ref: `${kind}:1`
  };
}

describe('memory helpers', () => {
  it('groups hits in the stable display order', () => {
    const groups = groupByKind([
      hit('question'),
      hit('tutor_turn'),
      hit('vault_note'),
      hit('learner_output'),
      hit('source_doc')
    ]);

    expect(groups.map((group) => group.kind)).toEqual([
      'vault_note',
      'source_doc',
      'learner_output',
      'tutor_turn',
      'question'
    ]);
    expect(groups.every((group) => group.hits.length === 1)).toBe(true);
  });

  it('places unknown kinds after known kinds', () => {
    const groups = groupByKind([hit('paper'), hit('question'), hit('artifact')]);

    expect(groups.map((group) => group.kind)).toEqual(['question', 'artifact', 'paper']);
  });

  it('normalizes whitespace and trims snippets to the requested length', () => {
    expect(trimSnippet('  spaced\n\ntext  ', 40)).toBe('spaced text');
    expect(trimSnippet('abcdefghijk', 10)).toBe('abcdefghi…');
  });
});
