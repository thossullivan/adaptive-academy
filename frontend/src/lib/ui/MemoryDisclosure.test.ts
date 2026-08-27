import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import type { MemoryHit } from '$lib/types';
import MemoryDisclosure from './MemoryDisclosure.svelte';

const hits: MemoryHit[] = [
  {
    chunk_id: 1,
    kind: 'vault_note',
    heading: 'Retrieval notes',
    snippet: 'A compact note about retrieval practice.',
    score: 0.91,
    source_ref: 'file:///vault/retrieval.md'
  },
  {
    chunk_id: 2,
    kind: 'learner_output',
    heading: 'Prior explanation',
    snippet: 'The learner connected recall with durable memory.',
    score: 0.72,
    source_ref: 'message:12'
  }
];

describe('MemoryDisclosure', () => {
  it('renders collapsed with the hit count', () => {
    const { body } = render(MemoryDisclosure, { props: { hits } });

    expect(body).toContain('What it remembered (2)');
    expect(body).not.toContain('Retrieval notes');
    expect(body).not.toContain('aria-expanded="true"');
  });

  it('lists kind badges, headings, and snippets when expanded', () => {
    const { body } = render(MemoryDisclosure, { props: { hits, expanded: true } });

    expect(body).toContain('aria-expanded="true"');
    expect(body).toContain('vault note');
    expect(body).toContain('Retrieval notes');
    expect(body).toContain('A compact note about retrieval practice.');
    expect(body).toContain('learner output');
    expect(body).toContain('Prior explanation');
  });

  it('renders nothing when hits are empty', () => {
    const { body } = render(MemoryDisclosure, { props: { hits: [] } });

    expect(body.replaceAll(/<!--.*?-->/g, '')).toBe('');
  });
});
