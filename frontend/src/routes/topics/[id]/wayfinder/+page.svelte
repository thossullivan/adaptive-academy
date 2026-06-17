<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { topics } from '$lib/topics.svelte';
  import type { Curriculum } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button } from '$lib/ui';
  import Wayfinder from '$lib/charts/Wayfinder.svelte';

  const topicId = Number($page.params.id);
  let loading = $state(true);
  let hasCurriculum = $state(false);
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

    // Display order: future (near the star) → past (the start line).
    wayPhases = withStatus.reverse();
    loading = false;
  });
</script>

<Page eyebrow="Wayfinder" title="Chart your voyage" lead="Your goal is the North Star. Each phase is a waypoint you steer toward — here's where you stand and what to aim for next." width="normal">
  {#snippet actions()}
    <Button variant="outline" href="/topics/{topicId}/map">Constellation</Button>
    <Button href="/topics/{topicId}/today">Today's session →</Button>
  {/snippet}

  {#if loading}
    <div class="grid place-items-center py-24"><span class="eyebrow animate-pulse">plotting the course…</span></div>
  {:else if !hasCurriculum}
    <Card accent pad class="text-center">
      <div class="py-10">
        <h2 class="text-xl text-fg">No course to chart yet</h2>
        <p class="mx-auto mt-2 max-w-sm text-sm text-muted">Generate a curriculum and your voyage will take shape.</p>
        <div class="mt-6"><Button href="/topics/{topicId}/review">Go to Sources →</Button></div>
      </div>
    </Card>
  {:else}
    <div class="rise">
      <Wayfinder {goal} phases={wayPhases} {nextItem} {reached} {topicId} />
    </div>
  {/if}
</Page>
