<script lang="ts">
  import type { EventOut } from '$lib/types';

  let { events = [], limit = 0 }: { events?: EventOut[]; limit?: number } = $props();

  const shown = $derived(limit ? events.slice(-limit).reverse() : [...events].reverse());

  // Map an event kind to a tone color.
  function tone(kind: string): string {
    if (kind.includes('error') || kind.includes('blocked')) return 'var(--danger)';
    if (kind.includes('allowed') || kind.includes('graded') || kind.includes('done')) return 'var(--success)';
    if (kind.startsWith('tool:') || kind.includes('llm')) return 'var(--accent)';
    if (kind.includes('subagent') || kind.includes('research')) return 'var(--info)';
    return 'var(--muted)';
  }
</script>

{#if shown.length}
  <ul class="flex flex-col gap-px">
    {#each shown as e, i (i)}
      <li class="group flex items-start gap-3 rounded-[var(--radius-xs)] px-2 py-1.5 transition-colors hover:bg-surface-2">
        <span class="mt-1.5 size-1.5 shrink-0 rounded-full" style:background={tone(e.kind)}></span>
        <code class="shrink-0 font-mono text-[0.7rem] text-fg-dim">{e.kind}</code>
        {#if e.detail}<span class="truncate text-xs text-faint">{e.detail}</span>{/if}
      </li>
    {/each}
  </ul>
{:else}
  <p class="px-2 py-3 text-sm text-faint">No activity yet.</p>
{/if}
