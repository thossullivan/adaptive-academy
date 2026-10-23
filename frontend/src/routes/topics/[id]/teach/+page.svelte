<script lang="ts">
  import { announce } from '$lib/text';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { toasts } from '$lib/toast.svelte';
  import { api } from '$lib/api';
  import type { Concept, Assessment, TeachResult } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Select, Textarea, LiveStatus } from '$lib/ui';

  const topicId = Number($page.params.id);
  let concepts = $state<Concept[]>([]);
  let conceptId = $state<number | null>(null);
  let taught = $state<Set<number>>(new Set());
  let explanation = $state('');
  let result = $state<TeachResult | null>(null);
  let busy = $state(false);
  let status = $state('');

  onMount(async () => {
    try {
      const cur = await api.getCurriculum(topicId);
      concepts = cur.concepts;
      conceptId = cur.concepts[0]?.id ?? null;
      // Mark concepts that already have a graded teaching artifact.
      const lists = await Promise.all(
        cur.concepts.map((c) => api.listAssessments(c.id).catch(() => [] as Assessment[]))
      );
      const t = new Set<number>();
      cur.concepts.forEach((c, i) => {
        if (lists[i].some((a) => a.kind === 'teach')) t.add(c.id);
      });
      taught = t;
    } catch {
      concepts = [];
    }
  });

  const conceptName = $derived(concepts.find((c) => c.id === conceptId)?.name ?? '');

  $effect(() => {
    conceptId;
    result = null;
    explanation = '';
  });

  async function submit() {
    if (conceptId == null || !explanation.trim()) return;
    busy = true;
    try {
      result = await api.gradeTeaching(conceptId, explanation);
      taught = new Set([...taught, conceptId]);
      status = announce(status, `Teaching review ready: ${Math.round(result.score * 100)}%.`);
    } catch (e) {
      toasts.show(e instanceof Error ? e.message : String(e), 'error', 9000);
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>Teach · Adaptive Academy</title></svelte:head>

<LiveStatus message={status} />

<Page eyebrow="Learn" title="Teach it" lead="Explain a concept as if you were teaching it, and get feedback on what came across and what didn't. Teaching is one of the best ways to find the gaps in what you know." width="normal">
  {#snippet actions()}
    <Select bind:value={conceptId} class="w-auto min-w-56 max-w-[min(24rem,calc(100vw-3rem))]" aria-label="Concept to teach" data-testid="concept-picker">
      {#each concepts as c (c.id)}<option value={c.id}>{c.name}{taught.has(c.id) ? ' ✓' : ''}</option>{/each}
    </Select>
  {/snippet}

  {#if !concepts.length}
    <Card pad class="text-center"><p class="py-8 text-sm text-muted">No concepts to teach yet. Make a track on the Sources page first.</p></Card>
  {:else}
    <div class="grid gap-4 lg:grid-cols-5">
      <Card class="lg:col-span-3" pad>
        <div class="flex items-center gap-2">
          <span class="eyebrow">your lesson</span>
          {#if conceptId != null && taught.has(conceptId)}<Badge tone="success" dot>taught</Badge>{/if}
        </div>
        <p class="mt-2 text-sm text-fg">
          Explain <b>{conceptName}</b> to a sharp friend who has never seen it. They will ask questions, so be clear about <i>how it works</i>, not just the terms.
        </p>
        <Textarea
          class="mt-3"
          bind:value={explanation}
          rows={12}
          aria-label="Your explanation of {conceptName}"
          placeholder="Imagine you're writing the explanation you wish you'd had…"
        />
        <Button class="mt-3" onclick={submit} disabled={busy || !explanation.trim() || conceptId == null}>
          {busy ? 'Grading the lesson…' : 'Submit for review'}
        </Button>
      </Card>

      <div class="lg:col-span-2">
        {#if result}
          <Card accent pad class="rise sticky top-6">
            <div class="flex items-center justify-between">
              <span class="eyebrow">teaching review</span>
              <Badge tone={result.score >= 0.7 ? 'success' : result.score >= 0.45 ? 'accent' : 'danger'} dot>{Math.round(result.score * 100)}%</Badge>
            </div>
            <p class="mt-3 text-sm leading-relaxed text-fg-dim">{result.feedback}</p>
            {#if result.strengths.length}
              <div class="mt-4">
                <span class="eyebrow text-success">landed</span>
                <ul class="mt-1.5 flex flex-col gap-1">
                  {#each result.strengths as s}<li class="flex items-start gap-2 text-sm text-muted"><span class="text-success" aria-hidden="true">✓</span>{s}</li>{/each}
                </ul>
              </div>
            {/if}
            {#if result.gaps.length}
              <div class="mt-4">
                <span class="eyebrow text-warn">a learner would still ask</span>
                <ul class="mt-1.5 flex flex-col gap-1">
                  {#each result.gaps as g}<li class="flex items-start gap-2 text-sm text-muted"><span class="text-warn" aria-hidden="true">?</span>{g}</li>{/each}
                </ul>
              </div>
            {/if}
          </Card>
        {:else}
          <Card pad class="grid h-full min-h-48 place-items-center text-center">
            <p class="text-sm text-faint">Your feedback will appear here: what came across, and what a reader would still find confusing.</p>
          </Card>
        {/if}
      </div>
    </div>
  {/if}
</Page>
