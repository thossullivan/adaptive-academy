import { describe, expect, it } from 'vitest';
import { EDGE_LEGEND, edgeToLink } from './graph';

describe('concept graph helpers', () => {
  it('maps API edges to constellation links without name matching', () => {
    expect(edgeToLink({ src: 8, dst: 3, kind: 'prerequisite', weight: 0.75 })).toEqual({
      source: 3,
      target: 8,
      kind: 'prerequisite',
      weight: 0.75
    });
  });

  it('labels the visible edge kinds', () => {
    expect(EDGE_LEGEND).toEqual([
      { kind: 'prerequisite', label: 'Prerequisite' },
      { kind: 'related', label: 'Related' }
    ]);
  });
});
