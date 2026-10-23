<script lang="ts">
  import type { EventOut } from '$lib/types';
  import { collapseEvents, plainEvents, timeAgo, type EventTone } from '$lib/events';

  let {
    events = [],
    limit = 0,
    mode = 'raw',
    concepts = {}
  }: {
    events?: EventOut[];
    limit?: number;
    /** 'raw': the agent trace as recorded (kind + detail), for the Sources and Tutor traces.
     *  'plain': only the events that mean something to a learner, each as a short sentence. */
    mode?: 'raw' | 'plain';
    /** Concept id to name, so a plain sentence can name the concept an event points at. */
    concepts?: Record<number, string>;
  } = $props();

  // Fold repeats (e.g. vault:export ×4) before limiting, so the limit counts distinct rows.
  const rows = $derived(collapseEvents(events));
  const shown = $derived(limit ? rows.slice(-limit).reverse() : [...rows].reverse());
  const plainRows = $derived(plainEvents(events, concepts));
  const plainShown = $derived(limit ? plainRows.slice(-limit).reverse() : [...plainRows].reverse());

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

  const TONE: Record<EventTone, string> = {
    good: 'var(--success)',
    warn: 'var(--warn)',
    bad: 'var(--danger)',
    neutral: 'var(--muted)'
  };
</script>

{#if mode === 'plain'}
  {#if plainShown.length}
    <ul class="flex flex-col gap-px" data-testid="event-feed-plain">
      {#each plainShown as e, i (i)}
        {@const ago = timeAgo(e.created_at)}
        <!-- The raw events behind each sentence stay one hover away for anyone tracing an agent. -->
        <li class="flex items-start gap-3 rounded-[var(--radius-xs)] px-2 py-1.5 transition-colors hover:bg-surface-2" title={e.raw}>
          <span class="mt-1.5 size-1.5 shrink-0 rounded-full" style:background={TONE[e.tone]} aria-hidden="true"></span>
          <span class="min-w-0 flex-1 text-sm text-fg-dim">{e.text}</span>
          {#if e.count > 1}
            <span class="nums shrink-0 text-xs text-muted" aria-label="{e.count} times" data-testid="event-count">×{e.count}</span>
          {/if}
          {#if ago}
            <time class="shrink-0 pl-2 text-xs text-faint" datetime={e.created_at}>{ago}</time>
          {/if}
        </li>
      {/each}
    </ul>
  {:else if events.length}
    <!-- Only bookkeeping so far (prompt tags, checks): say so rather than "nothing happened". -->
    <p class="px-2 py-3 text-sm text-faint">Nothing to summarize yet. The raw trace lists every agent step.</p>
  {:else}
    <p class="px-2 py-3 text-sm text-faint">No activity yet.</p>
  {/if}
{:else if shown.length}
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
