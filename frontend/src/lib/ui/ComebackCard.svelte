<script lang="ts">
  import type { WindState, Comeback } from '$lib/types';
  import { comebackTone } from '$lib/wind';
  import { clipWords } from '$lib/text';
  import Card from './Card.svelte';
  import Button from './Button.svelte';
  import Icon from '$lib/shell/Icon.svelte';

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
  // No track yet (engine/momentum.py comeback_move): the one move is building it.
  const uncharted = $derived(comeback.move?.kind === 'build_track');
</script>

{#if tone && comeback.move}
  {@const eyebrow = uncharted ? 'Getting started' : tone === 'launch' ? 'Ready to sail' : tone === 'warm' ? 'Becalmed' : 'Catching a breeze'}
  <Card class="rise">
    <div class="eyebrow mb-1 flex items-center gap-1.5">
      <Icon name={tone === 'warm' ? 'flag' : 'ship'} class="size-3.5 shrink-0" />{eyebrow}
    </div>
    {#if uncharted}
      <h2 class="font-display text-lg text-fg">Your voyage isn't charted yet.</h2>
      <p class="mt-1 text-sm text-muted">There is no track for this topic yet. Build one from your reading list to get started.</p>
    {:else if tone === 'launch'}
      <h2 class="font-display text-lg text-fg">Your voyage is charted.</h2>
      <p class="mt-1 text-sm text-muted">Take the first step and you're under way. One good move sets the sails.</p>
    {:else if tone === 'warm'}
      <h2 class="font-display text-lg text-fg">Your voyage is waiting.</h2>
      <p class="mt-1 text-sm text-muted">It's been {days} days. No matter: one good move catches the wind again.</p>
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
      <Icon name="ship" class="size-4 shrink-0" />{uncharted ? 'Go to Sources' : tone === 'warm' ? 'Catch the wind' : 'Set sail'}
    </Button>
  </Card>
{/if}
