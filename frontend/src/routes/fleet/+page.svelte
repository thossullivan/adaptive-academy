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

  // Never-sailed voyages sort last (API attention order); mark where that bucket begins.
  const firstUnsailed = $derived(fleet.findIndex((w) => w.state === 'unsailed'));

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
        <!-- Even horizontal spread (no colliding hash). Height = progress toward the North Star;
             liveliness (opacity) = momentum — so a far-along-but-stalled voyage sits high yet dim.
             Parked voyages stay quiet at the harbor floor and reveal their name only on hover. -->
        <a
          href={`/topics/${w.topic_id}/wayfinder`}
          class="group absolute flex -translate-x-1/2 flex-col items-center transition-transform hover:z-10 hover:scale-110"
          style={`left:${8 + ((i + 0.5) / fleet.length) * 84}%; bottom:${8 + w.progress * 64 + ((i % 3) - 1) * 3}%; opacity:${0.4 + seaIntensity(w.state) * 0.6}`}
        >
          <span class="text-xl">⛵</span>
          <span
            class="eyebrow max-w-[120px] truncate transition-opacity {w.state === 'unsailed' ? 'opacity-0 group-hover:opacity-100' : ''}"
            style:color={STATE_COLOR[w.state]}>{w.topic_title}</span>
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
      {#each fleet as w, i (w.topic_id)}
        {#if i === firstUnsailed && i > 0}
          <div class="mt-3 flex items-center gap-3 px-1">
            <span class="eyebrow text-faint">Not yet sailed</span>
            <span class="h-px flex-1 bg-border"></span>
          </div>
        {/if}
        <a href={`/topics/${w.topic_id}/wayfinder`} class="block">
          <Card pad class="transition-colors hover:border-accent">
            <div class="flex items-center gap-3">
              <span class="text-lg" style:opacity={0.4 + seaIntensity(w.state) * 0.6}>⛵</span>
              <span class="flex-1 truncate text-sm text-fg-dim">{w.topic_title}</span>
              {#if w.progress > 0}
                <div class="hidden items-center gap-1.5 sm:flex" title="{Math.round(w.progress * 100)}% toward the North Star">
                  <span class="h-1 w-14 overflow-hidden rounded-full bg-border">
                    <span class="block h-full rounded-full bg-accent" style:width={`${Math.round(w.progress * 100)}%`}></span>
                  </span>
                  <span class="eyebrow text-faint">{Math.round(w.progress * 100)}%</span>
                </div>
              {/if}
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
