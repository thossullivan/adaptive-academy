<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { topics } from '$lib/topics.svelte';
  import type { WindState } from '$lib/types';
  import { STATE_LABEL, STATE_COLOR, seaIntensity } from '$lib/wind';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button } from '$lib/ui';
  import Icon from '$lib/shell/Icon.svelte';

  let fleet = $state<WindState[]>([]);
  let loading = $state(true);
  // Harbor (one shared sea) or tiles (a list). With only a ship or two the harbor is mostly
  // empty water, so tiles are the default until the fleet has three voyages; a view the
  // learner picks wins either way.
  const MIN_HARBOR = 3;
  const VIEWS = [
    { value: 'harbor', label: 'Harbor' },
    { value: 'tiles', label: 'Tiles' }
  ] as const;
  let chosenView = $state<'harbor' | 'tiles' | null>(null);
  const view = $derived(chosenView ?? (fleet.length >= MIN_HARBOR ? 'harbor' : 'tiles'));
  const panorama = $derived(view === 'harbor');

  // Never-sailed voyages sort last (API attention order); mark where that bucket begins.
  const firstUnsailed = $derived(fleet.findIndex((w) => w.state === 'unsailed'));

  // Empty fleet: the same one-click demo the home screen offers.
  let demoBusy = $state(false);
  let demoError = $state('');
  async function exploreDemo() {
    demoBusy = true;
    demoError = '';
    try {
      await topics.openDemo();
      await goto('/');
    } catch (e) {
      demoError = `Couldn't load the demo: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      demoBusy = false;
    }
  }

  onMount(async () => {
    try {
      fleet = await api.getFleet();
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head><title>Fleet · Adaptive Academy</title></svelte:head>

<Page
  eyebrow="All topics"
  title="The Fleet"
  lead="All your topics in one place. The ones you haven't worked on lately come first."
>
  {#snippet actions()}
    <!-- Nothing to collapse until there is a fleet. -->
    {#if !loading && fleet.length}
      <div
        role="group"
        aria-label="Fleet view"
        class="flex h-9 items-center gap-0.5 rounded-[var(--radius-sm)] border border-border bg-surface-2 p-0.5"
        data-testid="fleet-view"
      >
        {#each VIEWS as v (v.value)}
          <button
            type="button"
            aria-pressed={view === v.value}
            onclick={() => (chosenView = v.value)}
            class="flex h-full items-center rounded-[var(--radius-xs)] px-3 text-xs transition-colors {view === v.value
              ? 'bg-surface text-fg ring-1 ring-control-border'
              : 'text-muted hover:text-fg'}"
          >{v.label}</button>
        {/each}
      </div>
    {/if}
  {/snippet}

  {#if loading}
    <p class="py-10 text-center text-sm text-faint" role="status">Charting the seas…</p>
  {:else if !fleet.length}
    <Card pad class="text-center" data-testid="fleet-empty">
      <div class="py-8">
        <h2 class="text-xl text-fg">No voyages yet</h2>
        <p class="mx-auto mt-2 max-w-sm text-sm text-muted">Every topic you start sets a ship on this sea. Start one, or look around a worked example first.</p>
        <div class="mt-6 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
          <Button href="/topics/new">Start a topic →</Button>
          <Button variant="outline" onclick={exploreDemo} disabled={demoBusy}>
            {demoBusy ? 'Loading the demo…' : 'Explore a demo topic'}
          </Button>
        </div>
        <p class="mt-3 text-xs text-faint">The demo needs no API key, and you can remove it later.</p>
        {#if demoError}<p class="mt-2 text-xs text-danger" role="alert">{demoError}</p>{/if}
      </div>
    </Card>
  {:else if panorama}
    <!-- Hero: one shared ocean; ship height = momentum -->
    <!-- Each ship is a link whose name says what its position and brightness show. -->
    <figure
      class="relative h-[420px] overflow-hidden rounded-[var(--radius)] border border-border"
      style="background:radial-gradient(120% 90% at 50% -10%, color-mix(in oklab,var(--accent) 8%, var(--surface)) 0%, var(--bg) 70%)"
      aria-label="The fleet: {fleet.length} voyage{fleet.length === 1 ? '' : 's'}. A ship sits higher the closer it is to its North Star, and brighter the more momentum it has."
      data-testid="fleet-panorama"
    >
      <div class="absolute left-1/2 top-3 flex -translate-x-1/2 flex-col items-center gap-1 text-center" aria-hidden="true">
        <Icon name="wayfinder" class="size-6 text-accent" />
        <div class="eyebrow">North Star</div>
      </div>
      {#each fleet as w, i (w.topic_id)}
        <!-- Even horizontal spread (no colliding hash). Height = progress toward the North Star;
             liveliness (opacity) = momentum — so a far-along-but-stalled voyage sits high yet dim.
             Parked voyages stay quiet at the harbor floor and reveal their name only on hover. -->
        <a
          href={`/topics/${w.topic_id}/wayfinder`}
          aria-label="{w.topic_title}: {STATE_LABEL[w.state]}, {Math.round(w.progress * 100)}% toward the North Star"
          title={w.topic_title}
          class="group absolute flex -translate-x-1/2 flex-col items-center transition-transform hover:z-10 hover:scale-110 focus-visible:z-10 focus-visible:!opacity-100 motion-reduce:transition-none motion-reduce:hover:scale-100"
          style={`left:${8 + ((i + 0.5) / fleet.length) * 84}%; bottom:${8 + w.progress * 64 + ((i % 3) - 1) * 3}%; opacity:${0.4 + seaIntensity(w.state) * 0.6}`}
        >
          <span style:color={STATE_COLOR[w.state]}><Icon name="ship" class="size-6" /></span>
          <!-- The name in sentence case, wrapped to two lines at most (the title has all of it). -->
          <span
            class="mt-0.5 line-clamp-2 w-max max-w-[10rem] break-words text-center text-xs font-medium leading-snug transition-opacity {w.state === 'unsailed' ? 'opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100' : ''}"
            style:color={STATE_COLOR[w.state]}
            data-testid="fleet-ship-name">{w.topic_title}</span>
        </a>
      {/each}
      <div
        class="pointer-events-none absolute inset-x-0 bottom-0 h-16"
        aria-hidden="true"
        style="background:linear-gradient(180deg, transparent, color-mix(in oklab, var(--bg) 70%, transparent))"
      ></div>
    </figure>
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
              <span class="shrink-0" style:color={STATE_COLOR[w.state]} style:opacity={0.4 + seaIntensity(w.state) * 0.6}><Icon name="ship" class="size-5" /></span>
              <span class="min-w-0 flex-1 break-words text-sm text-fg-dim">{w.topic_title}</span>
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
