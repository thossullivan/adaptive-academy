<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { topics } from '$lib/topics.svelte';
  import type { Curriculum, WindState } from '$lib/types';
  import { seaIntensity, STATE_LABEL, STATE_COLOR } from '$lib/wind';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button } from '$lib/ui';
  import Wayfinder from '$lib/charts/Wayfinder.svelte';
  import Icon from '$lib/shell/Icon.svelte';

  const topicId = Number($page.params.id);
  let loading = $state(true);
  let hasCurriculum = $state(false);
  let wind = $state<WindState | null>(null);
  let goal = $state('');
  let reached = $state(false);
  let nextItem = $state<{ text: string; phaseTitle: string } | null>(null);
  let wayPhases = $state<
    {
      id: number; position: number; title: string; est_hours: string; flags: string[];
      done: number; total: number; status: 'traversed' | 'current' | 'ahead';
      deliverable: { kind: string; text: string } | null;
    }[]
  >([]);

  onMount(async () => {
    // North Star = the topic's stated goal.
    const topic = topics.list.find((t) => t.id === topicId) ?? (await api.getTopic(topicId).catch(() => null));
    goal = topic?.intent?.goal ?? topic?.title ?? '';
    wind = await api.getWind(topicId).catch(() => null);

    let cur: Curriculum;
    try {
      cur = await api.getCurriculum(topicId);
      hasCurriculum = true;
    } catch {
      loading = false;
      return;
    }

    const ordered = [...cur.phases].sort((a, b) => a.position - b.position);
    const computed = ordered.map((p) => {
      const done = p.items.filter((it) => it.status === 'done').length;
      return { p, done, total: p.items.length, isDone: p.items.length > 0 && done === p.items.length };
    });

    // Current = first phase not fully done; before = traversed, after = ahead.
    const currentIdx = computed.findIndex((c) => !c.isDone);
    // "Arrived" only when there ARE phases and every one is charted — not when empty.
    reached = computed.length > 0 && currentIdx === -1;

    if (currentIdx !== -1) {
      const cp = computed[currentIdx].p;
      const next = cp.items.find((it) => it.status !== 'done');
      if (next) nextItem = { text: next.text, phaseTitle: cp.title };
    }

    const withStatus = computed.map((c, i) => ({
      id: c.p.id,
      position: c.p.position,
      title: c.p.title,
      est_hours: c.p.est_hours,
      flags: c.p.flags,
      done: c.done,
      total: c.total,
      status: (currentIdx === -1 || i < currentIdx
        ? 'traversed'
        : i === currentIdx
          ? 'current'
          : 'ahead') as 'traversed' | 'current' | 'ahead',
      deliverable: c.p.deliverable ? { kind: c.p.deliverable.kind, text: c.p.deliverable.text } : null
    }));

    // Ascending: Phase 1 at the top, the journey descending toward the North Star (the
    // destination) at the bottom.
    wayPhases = withStatus;
    loading = false;
  });
</script>

<svelte:head><title>Wayfinder · Adaptive Academy</title></svelte:head>

<Page eyebrow="Wayfinder" title="Chart your voyage" lead="Your goal is the North Star. Each phase is a waypoint you steer toward — here's where you stand and what to aim for next." width="normal">
  {#snippet actions()}
    <Button variant="outline" href="/topics/{topicId}/map">Constellation</Button>
    <Button href="/topics/{topicId}/today">Today's session →</Button>
  {/snippet}

  {#if loading}
    <div class="grid place-items-center py-24" role="status"><span class="eyebrow animate-pulse">plotting the course…</span></div>
  {:else if !hasCurriculum}
    <Card accent pad class="text-center">
      <div class="py-10">
        <h2 class="text-xl text-fg">No course to chart yet</h2>
        <p class="mx-auto mt-2 max-w-sm text-sm text-muted">Generate a curriculum and your voyage will take shape.</p>
        <div class="mt-6"><Button href="/topics/{topicId}/review">Go to Sources →</Button></div>
      </div>
    </Card>
  {:else}
    {#if wind}
      <div class="mb-3 flex items-center gap-2">
        <span class="eyebrow flex items-center gap-1.5" style:color={STATE_COLOR[wind.state]}><Icon name="ship" class="size-3.5 shrink-0" />{STATE_LABEL[wind.state]}</span>
        {#if wind.days_since != null}<span class="eyebrow text-faint">· last sailed {Math.round(wind.days_since)}d ago</span>{/if}
      </div>
      <div class="sea pointer-events-none" style={`--swell:${seaIntensity(wind.state)}`} aria-hidden="true">
        <div class="wave"></div>
        <div class="wave wave2"></div>
      </div>
    {/if}
    <div class="rise">
      <Wayfinder {goal} phases={wayPhases} {nextItem} {reached} {topicId} />
    </div>
  {/if}
</Page>

<style>
  /* Sea-state band: still and flat when becalmed (--swell 0), lively when cruising (--swell 1). */
  .sea {
    position: relative;
    height: calc(8px + var(--swell) * 22px);
    opacity: calc(0.25 + var(--swell) * 0.6);
    margin-bottom: 1rem;
    overflow: hidden;
    border-radius: var(--radius-sm);
  }
  .wave {
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(
      90deg,
      transparent,
      transparent 18px,
      color-mix(in oklab, var(--accent) 30%, transparent) 19px,
      transparent 20px
    );
    animation: drift calc(6s - var(--swell) * 3s) linear infinite;
  }
  .wave2 {
    opacity: 0.5;
    animation-duration: calc(9s - var(--swell) * 3s);
  }
  @keyframes drift {
    to {
      transform: translateX(-40px);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .wave {
      animation: none;
    }
  }
</style>
