import { render } from 'svelte/server';
import { describe, expect, it, vi } from 'vitest';
import type { MemoryHit, MemoryReindexResult } from '$lib/types';
import MemorySearchResults from './MemorySearchResults.svelte';
import { REINDEX_FAILURE_TOAST, runMemoryReindex, runMemorySearch } from './memory-actions';

function hit(chunkId: number, kind: string): MemoryHit {
  return {
    chunk_id: chunkId,
    kind,
    heading: `${kind} heading`,
    snippet: `${kind} snippet`,
    score: 1,
    source_ref: `${kind}:${chunkId}`
  };
}

describe('vault memory search', () => {
  it('clamps a typed result limit above 50 before searching', async () => {
    const searchMemory = vi.fn().mockResolvedValue({ hits: [] });

    const result = await runMemorySearch(searchMemory, '  retrieval  ', 7, '60');

    expect(searchMemory).toHaveBeenCalledWith('retrieval', { topic_id: 7, k: 50 });
    expect(result.k).toBe(50);
  });

  it('shows the empty state only after a search has completed', () => {
    const typed = render(MemorySearchResults, {
      props: { hits: [], query: 'retrieval', searched: false, searching: false }
    });
    const searched = render(MemorySearchResults, {
      props: { hits: [], query: 'retrieval', searched: true, searching: false }
    });

    expect(typed.body).not.toContain('No indexed memory matches this search.');
    expect(searched.body).toContain('No indexed memory matches this search.');
  });

  it('renders search results grouped in stable kind order', () => {
    const { body } = render(MemorySearchResults, {
      props: {
        hits: [hit(1, 'question'), hit(2, 'vault_note'), hit(3, 'learner_output')],
        query: 'retrieval',
        searched: true,
        searching: false
      }
    });

    expect(body.indexOf('vault note')).toBeLessThan(body.indexOf('learner output'));
    expect(body.indexOf('learner output')).toBeLessThan(body.indexOf('question'));
    expect(body).toContain('vault_note heading');
    expect(body).toContain('question snippet');
  });
});

describe('vault memory reindex', () => {
  it('shows the successful reindex counts', async () => {
    const result: MemoryReindexResult = {
      indexed: 3,
      skipped: 4,
      removed: 1,
      truncated: false,
      ms: 25
    };
    const reindexMemory = vi.fn().mockResolvedValue(result);
    const showToast = vi.fn();

    await expect(
      runMemoryReindex(reindexMemory, { topic_id: 7, vault_path: '/vault' }, showToast)
    ).resolves.toEqual(result);
    expect(showToast).toHaveBeenCalledWith('Reindex complete: 3 indexed, 4 skipped, 1 removed.');
  });

  it('shows the failure toast and preserves the error', async () => {
    const error = new Error('no vault path configured');
    const reindexMemory = vi.fn().mockRejectedValue(error);
    const showToast = vi.fn();

    await expect(runMemoryReindex(reindexMemory, { topic_id: 7 }, showToast)).rejects.toBe(error);
    expect(showToast).toHaveBeenCalledWith(REINDEX_FAILURE_TOAST, 'error');
  });
});
