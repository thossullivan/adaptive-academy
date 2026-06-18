<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { WindState } from '$lib/types';
  import { STATE_LABEL, STATE_COLOR, seaIntensity } from '$lib/wind';
  import Page from '$lib/shell/Page.svelte';
  import { Card } from '$lib/ui';

  let fleet = $state<WindState[]>([]);
  let loading = $state(true);
  let panorama = $state(true); // hero panorama vs. collapsed sea-tiles

  onMount(async () => {
    try {
      fleet = await api.getFleet();
    } finally {
      loading = false;
    }
  });
</script>

<Page
  eyebrow="Voyages"
  title="The Fleet"
  lead="Your whole learning life at a glance. Becalmed voyages need wind; cruising ones just hum along."
>
  {#snippet actions()}
    <button class="eyebrow transition-colors hover:text-fg" onclick={() => (panorama = !panorama)}>
      {panorama ? 'Collapse to tiles' : 'Show harbor'}
    </button>
  {/snippet}

  {#if loading}
    <p class="py-10 text-center text-sm text-faint">Charting the seas…</p>
  {:else if !fleet.length}
    <p class="py-10 text-center text-sm text-faint">No voyages yet. Create a topic to set sail.</p>
  {:else if panorama}
    <!-- Hero: one shared ocean; ship height = momentum -->
    <div
      class="relative h-[420px] overflow-hidden rounded-[var(--radius)] border border-border"
      style="background:radial-gradient(120% 90% at 50% -10%, color-mix(in oklab,var(--accent) 8%, var(--surface)) 0%, var(--bg) 70%)"
    >
      <div class="absolute left-1/2 top-3 -translate-x-1/2 text-center">
        <div class="text-2xl">⭐</div>
        <div class="eyebrow">North Star</div>
      </div>
      {#each fleet as w, i (w.topic_id)}
        <a
          href={`/topics/${w.topic_id}/wayfinder`}
          class="absolute flex flex-col items-center transition-transform hover:scale-110"
          style={`left:${6 + ((i * 37) % 80)}%; bottom:${10 + seaIntensity(w.state) * 62}%; opacity:${0.45 + seaIntensity(w.state) * 0.55}`}
        >
          <span class="text-xl">⛵</span>
          <span class="eyebrow whitespace-nowrap" style:color={STATE_COLOR[w.state]}>{w.topic_title}</span>
        </a>
      {/each}
      <div
        class="absolute inset-x-0 bottom-0 h-16"
        style="background:linear-gradient(180deg, transparent, color-mix(in oklab, var(--bg) 70%, transparent))"
      ></div>
    </div>
  {:else}
    <!-- Collapsed sea-tiles: becalmed first (already sorted by the API) -->
    <div class="flex flex-col gap-2">
      {#each fleet as w (w.topic_id)}
        <a href={`/topics/${w.topic_id}/wayfinder`} class="block">
          <Card pad class="transition-colors hover:border-accent">
            <div class="flex items-center gap-3">
              <span class="text-lg" style:opacity={0.4 + seaIntensity(w.state) * 0.6}>⛵</span>
              <span class="flex-1 truncate text-sm text-fg-dim">{w.topic_title}</span>
              {#if w.days_since != null}
                <span class="eyebrow text-faint">{Math.round(w.days_since)}d</span>
              {/if}
              <span class="eyebrow w-20 text-right" style:color={STATE_COLOR[w.state]}>{STATE_LABEL[w.state]}</span>
            </div>
          </Card>
        </a>
      {/each}
    </div>
  {/if}
</Page>
