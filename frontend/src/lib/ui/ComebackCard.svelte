<script lang="ts">
  import type { WindState, Comeback } from '$lib/types';
  import { comebackTone } from '$lib/wind';
  import { clipWords } from '$lib/text';
  import Card from './Card.svelte';
  import Button from './Button.svelte';

  let { wind, comeback }: { wind: WindState; comeback: Comeback } = $props();
  const tone = $derived(comebackTone(wind.state));
  const days = $derived(wind.days_since != null ? Math.round(wind.days_since) : 0);

  // The move is a curriculum item and can run long: clip on a word boundary (never mid-word)
  // and keep the whole text one tap away (and on hover via the title).
  const MOVE_MAX = 120;
  // Strip paired markdown emphasis and code ticks only: a bare `_` is part of identifiers
  // like log_softmax that ML curricula are full of.
  const label = $derived(
    (comeback.move?.label ?? '')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .trim()
  );
  const clipped = $derived(clipWords(label, MOVE_MAX));
  let expanded = $state(false);
</script>

{#if tone && comeback.move}
  {@const eyebrow = tone === 'launch' ? '⛵ Ready to sail' : tone === 'warm' ? '⚑ Becalmed' : '⛵ Catching a breeze'}
  <Card class="rise" {eyebrow}>
    {#if tone === 'launch'}
      <h2 class="font-display text-lg text-fg">Your voyage is charted.</h2>
      <p class="mt-1 text-sm text-muted">Take the first step and you're under way — one good move sets the sails.</p>
    {:else if tone === 'warm'}
      <h2 class="font-display text-lg text-fg">Your voyage is waiting.</h2>
      <p class="mt-1 text-sm text-muted">It's been {days} days — no matter. One good move catches the wind again.</p>
    {:else}
      <h2 class="font-display text-lg text-fg">A breeze on the horizon.</h2>
      <p class="mt-1 text-sm text-muted">The sails are stirring after {days} days. Take the helm and you're moving.</p>
    {/if}
    <div class="my-3 rounded-[var(--radius-sm)] border border-border bg-surface-2 px-3 py-2">
      <div class="eyebrow text-faint">Your one move · ~{comeback.move.minutes} min</div>
      <p class="mt-1 break-words text-sm text-fg-dim" title={clipped.clipped ? label : undefined}>
        {expanded ? label : clipped.text}
        {#if clipped.clipped}
          <button
            type="button"
            class="ml-1 whitespace-nowrap text-xs text-accent underline-offset-2 hover:underline"
            aria-expanded={expanded}
            onclick={() => (expanded = !expanded)}
          >{expanded ? 'Show less' : 'Show all'}</button>
        {/if}
      </p>
    </div>
    <Button size="sm" href={comeback.move.href}>
      {tone === 'warm' ? '⛵ Catch the wind' : '⛵ Set sail'}
    </Button>
  </Card>
{/if}
