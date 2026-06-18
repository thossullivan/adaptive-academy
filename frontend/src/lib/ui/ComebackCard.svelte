<script lang="ts">
  import type { WindState, Comeback } from '$lib/types';
  import { comebackTone } from '$lib/wind';
  import Card from './Card.svelte';
  import Button from './Button.svelte';

  let { wind, comeback }: { wind: WindState; comeback: Comeback } = $props();
  const tone = $derived(comebackTone(wind.state));
  const days = $derived(wind.days_since != null ? Math.round(wind.days_since) : 0);
</script>

{#if tone && comeback.move}
  <Card class="rise" eyebrow={tone === 'warm' ? '⚑ Becalmed' : '⛵ Catching a breeze'}>
    {#if tone === 'warm'}
      <h3 class="font-display text-lg text-fg">Your voyage is waiting.</h3>
      <p class="mt-1 text-sm text-muted">It's been {days} days — no matter. One good move catches the wind again.</p>
    {:else}
      <h3 class="font-display text-lg text-fg">A breeze on the horizon.</h3>
      <p class="mt-1 text-sm text-muted">The sails are stirring after {days} days. Take the helm and you're moving.</p>
    {/if}
    <div class="my-3 rounded-[var(--radius-sm)] border border-border bg-surface-2 px-3 py-2">
      <div class="eyebrow text-faint">Your one move · ~{comeback.move.minutes} min</div>
      <div class="mt-1 text-sm text-fg-dim">{comeback.move.label}</div>
    </div>
    <Button size="sm" href={comeback.move.href}>
      {tone === 'warm' ? '⛵ Catch the wind' : '⛵ Set sail'}
    </Button>
  </Card>
{/if}
