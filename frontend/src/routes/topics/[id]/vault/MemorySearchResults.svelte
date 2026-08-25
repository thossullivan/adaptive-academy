<script lang="ts">
  import { groupByKind, trimSnippet } from '$lib/memory';
  import type { MemoryHit } from '$lib/types';
  import { Badge } from '$lib/ui';

  let {
    hits,
    query,
    searched,
    searching
  }: {
    hits: MemoryHit[];
    query: string;
    searched: boolean;
    searching: boolean;
  } = $props();

  const groups = $derived(groupByKind(hits));
</script>

{#if groups.length}
  <div class="mt-5 flex flex-col gap-5">
    {#each groups as group (group.kind)}
      <section>
        <div class="mb-2 flex items-center gap-2">
          <Badge mono tone="neutral">{group.kind.replaceAll('_', ' ')}</Badge>
          <span class="nums text-xs text-faint">{group.hits.length}</span>
        </div>
        <ul class="flex flex-col divide-y divide-border rounded-[var(--radius-md)] border border-border bg-surface-2">
          {#each group.hits as hit (hit.chunk_id)}
            <li class="px-4 py-3">
              <div class="text-sm font-medium text-fg-dim">{hit.heading || hit.source_ref}</div>
              <p class="mt-1 text-xs leading-relaxed text-faint">{trimSnippet(hit.snippet)}</p>
            </li>
          {/each}
        </ul>
      </section>
    {/each}
  </div>
{:else if searched && query.trim() && !searching}
  <p class="mt-4 text-sm text-faint">No indexed memory matches this search.</p>
{/if}
