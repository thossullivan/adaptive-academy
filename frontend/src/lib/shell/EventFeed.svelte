<script lang="ts">
  import type { EventOut } from '$lib/types';
  import { collapseEvents, timeAgo } from '$lib/events';

  let { events = [], limit = 0 }: { events?: EventOut[]; limit?: number } = $props();

  // Fold repeats (e.g. vault:export ×4) before limiting, so the limit counts distinct rows.
  const rows = $derived(collapseEvents(events));
  const shown = $derived(limit ? rows.slice(-limit).reverse() : [...rows].reverse());

  // Map an event kind to a tone color.
  function tone(kind: string): string {
    if (kind.includes('error') || kind.includes('blocked')) return 'var(--danger)';
    if (kind.includes('allowed') || kind.includes('graded') || kind.includes('done') || kind === 'attempt:accepted')
      return 'var(--success)';
    if (kind === 'attempt:rejected' || kind === 'attempt:unverified') return 'var(--warn)';
    if (kind.startsWith('tool:') || kind.includes('llm')) return 'var(--accent)';
    if (kind.includes('subagent') || kind.includes('research')) return 'var(--info)';
    return 'var(--muted)';
  }
</script>

{#if shown.length}
  <ul class="flex flex-col gap-px">
    {#each shown as e, i (i)}
      {@const ago = timeAgo(e.created_at)}
      <li class="group flex items-start gap-3 rounded-[var(--radius-xs)] px-2 py-1.5 transition-colors hover:bg-surface-2">
        <span class="mt-1.5 size-1.5 shrink-0 rounded-full" style:background={tone(e.kind)}></span>
        <code class="shrink-0 font-mono text-[0.7rem] text-fg-dim">{e.kind}</code>
        {#if e.count > 1}
          <span class="nums shrink-0 font-mono text-[0.7rem] text-muted" aria-label="{e.count} times" data-testid="event-count">×{e.count}</span>
        {/if}
        {#if e.detail}<span class="min-w-0 truncate text-xs text-faint" title={e.detail}>{e.detail}</span>{/if}
        {#if ago}
          <time class="ml-auto shrink-0 pl-2 text-[0.7rem] text-faint" datetime={e.created_at}>{ago}</time>
        {/if}
      </li>
    {/each}
  </ul>
{:else}
  <p class="px-2 py-3 text-sm text-faint">No activity yet.</p>
{/if}
