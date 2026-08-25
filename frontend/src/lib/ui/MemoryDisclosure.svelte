<script lang="ts">
  import type { MemoryHit } from '$lib/types';
  import { trimSnippet } from '$lib/memory';
  import Badge from './Badge.svelte';
  import Card from './Card.svelte';

  let {
    hits = [],
    expanded = $bindable(false)
  }: {
    hits?: MemoryHit[];
    expanded?: boolean;
  } = $props();

  function label(kind: string): string {
    return kind.replaceAll('_', ' ');
  }
</script>

{#if hits.length}
  <div class="mt-1.5">
    <button
      type="button"
      class="eyebrow px-2 py-1 transition-colors hover:text-fg-dim"
      aria-expanded={expanded}
      onclick={() => (expanded = !expanded)}
    >
      {expanded ? '▾' : '▸'} What it remembered ({hits.length})
    </button>
    {#if expanded}
      <Card pad={false} class="mt-1 overflow-hidden">
        <ul class="flex flex-col divide-y divide-border">
          {#each hits as hit (hit.chunk_id)}
            <li class="px-3 py-2.5">
              <div class="flex flex-wrap items-center gap-2">
                <Badge mono tone="neutral">{label(hit.kind)}</Badge>
                <span class="text-xs font-medium text-fg-dim">{hit.heading || hit.source_ref}</span>
              </div>
              <p class="mt-1.5 text-xs leading-relaxed text-faint">{trimSnippet(hit.snippet)}</p>
            </li>
          {/each}
        </ul>
      </Card>
    {/if}
  </div>
{/if}
