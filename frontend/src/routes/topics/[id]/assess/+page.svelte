<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { toasts } from '$lib/toast.svelte';
  import { api } from '$lib/api';
  import type { Curriculum, Assessment } from '$lib/types';
  import { pct } from '$lib/utils';
  import { artifactOutcome, HELD, MILESTONE_ARTIFACT } from '$lib/competence';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Field, Select, Textarea, Markdown, LiveStatus } from '$lib/ui';

  const topicId = Number($page.params.id);
  let cur = $state<Curriculum | null>(null);
  let conceptId = $state<number | null>(null);
  let kind = $state('self_explanation');
  let response = $state('');
  let confidence = $state(70);
  let result = $state<Assessment | null>(null);
  let busy = $state(false);
  let anchorQuestion = $state<string | null>(null);
  let status = $state('');
  let runs = 0;

  const PROBES: { value: string; label: string; blurb: string }[] = [
    { value: 'self_explanation', label: 'Self-explanation', blurb: 'Explain the concept in your own words.' },
    { value: 'calibration', label: 'Calibration', blurb: 'Say how sure you are, then see how your grade compares.' },
    { value: 'artifact_review', label: 'Artifact review', blurb: 'Submit something you built for critique.' },
    { value: 'source_quiz', label: 'Source quiz', blurb: 'Answer a question written from one of your sources.' }
  ];

  onMount(async () => {
    try {
      cur = await api.getCurriculum(topicId);
    } catch {
      cur = null;
    }
    if (cur?.concepts.length) conceptId = cur.concepts[0].id;
  });

  let selectedConcept = $derived(cur?.concepts.find((c) => c.id === conceptId) ?? null);
  let activeProbe = $derived(PROBES.find((p) => p.value === kind)!);

  async function loadAnchor() {
    anchorQuestion = null;
    if (conceptId == null || kind !== 'source_quiz' || !selectedConcept?.has_anchor) return;
    try {
      const anchors = await api.listConceptAnchors(conceptId);
      anchorQuestion = anchors.length ? anchors[0].question : null;
    } catch {
      anchorQuestion = null;
    }
  }

  $effect(() => {
    conceptId;
    kind;
    loadAnchor();
  });

  let remediating = $state(false);
  let remediatedCount = $state<number | null>(null);
  async function remediate() {
    if (conceptId == null) return;
    remediating = true;
    try {
      const r = await api.remediate(conceptId);
      remediatedCount = r.items.length;
    } catch (e) {
      toasts.show(e instanceof Error ? e.message : String(e), 'error', 9000);
    } finally {
      remediating = false;
    }
  }

  async function run() {
    if (conceptId == null) return;
    busy = true;
    remediatedCount = null;
    try {
      result = await api.assess(conceptId, {
        kind,
        response,
        confidence_predicted: kind === 'calibration' ? confidence / 100 : null
      });
      const outcome = result.kind === 'artifact_review' ? artifactOutcome(result.score).label : (result.estimate_level ?? '');
      // A counter keeps a repeat of the same result distinct, so it is announced again.
      status = `Assessment ${++runs}: ${Math.round(result.score * 100)} out of 100${outcome ? `, ${outcome}` : ''}.`;
    } catch (e) {
      toasts.show(e instanceof Error ? e.message : String(e), 'error', 9000);
    } finally {
      busy = false;
    }
  }

  // An artifact review lights the "shipped" signal and never sets the grade (engine/assess.py
  // GRADING_KINDS), so its verdict is shipped ✓/✗ against the same threshold the dashboard uses.
  const artifact = $derived(result?.kind === 'artifact_review' ? artifactOutcome(result.score) : null);
  const scoreTone = $derived(
    result == null
      ? 'neutral'
      : artifact
        ? artifact.meetsGate ? 'success' : artifact.shipped ? 'warn' : 'danger'
        : result.score >= 0.7 ? 'success' : result.score >= 0.4 ? 'warn' : 'danger'
  );
</script>

<svelte:head><title>Assess · Adaptive Academy</title></svelte:head>

<Page eyebrow="Learn" title="Assess understanding" lead="Answer a question about a concept in your own words and get it graded. Writing the answer yourself shows what you really know." width="normal">
  <LiveStatus message={status} />
  {#if !cur}
    <Card accent pad class="text-center">
      <div class="py-10">
        <h2 class="text-xl text-fg">No curriculum yet</h2>
        <p class="mx-auto mt-2 max-w-sm text-sm text-muted">Make a track from your reading list first.</p>
        <div class="mt-6"><Button href="/topics/{topicId}/review">Go to Sources →</Button></div>
      </div>
    </Card>
  {:else if !cur.concepts.length}
    <Card pad class="text-center"><p class="py-8 text-sm text-muted">This topic has no tracked concepts to assess.</p></Card>
  {:else}
    <div class="grid gap-4 lg:grid-cols-5">
      <!-- Form -->
      <Card class="lg:col-span-3" pad>
        <div class="flex flex-col gap-4">
          <!-- Concept names run long, so the concept picker gets a row to itself. -->
          <div class="grid gap-4 sm:grid-cols-2">
            <div class="sm:col-span-2">
              <Field label="Concept">
                <Select bind:value={conceptId} data-testid="concept-picker">
                  {#each cur.concepts as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
                </Select>
              </Field>
            </div>
            <Field label="Probe">
              <Select bind:value={kind}>
                {#each PROBES as p}
                  {#if p.value !== 'source_quiz' || selectedConcept?.has_anchor}
                    <option value={p.value}>{p.label}</option>
                  {/if}
                {/each}
              </Select>
            </Field>
          </div>
          <p class="-mt-1 text-xs text-faint">{activeProbe.blurb}</p>

          {#if kind === 'calibration'}
            <Field label="How sure are you? {confidence}%">
              <input type="range" min="0" max="100" bind:value={confidence} aria-valuetext="{confidence}%" class="w-full accent-[var(--accent)]" />
            </Field>
          {/if}

          {#if kind === 'source_quiz' && anchorQuestion}
            <div class="rounded-[var(--radius-md)] border border-info/40 bg-[color-mix(in_oklab,var(--info)_8%,transparent)] p-3">
              <span class="eyebrow !text-info">question</span>
              <p class="mt-1 text-sm text-fg">{anchorQuestion}</p>
            </div>
          {/if}

          <Field label="Your response">
            <Textarea bind:value={response} rows={7} placeholder="Explain in your own words: the reasoning, how it works, the edge cases…" />
          </Field>

          <Button onclick={run} disabled={busy || conceptId == null} class="self-start">
            {busy ? 'Grading…' : 'Submit for assessment'}
          </Button>
        </div>
      </Card>

      <!-- Result -->
      <div class="lg:col-span-2">
        {#if result}
          <Card accent pad class="rise sticky top-6">
            <div class="flex items-center justify-between">
              <span class="eyebrow">verdict</span>
              {#if artifact}
                <span data-testid="artifact-outcome"><Badge tone={scoreTone} dot>{artifact.label}</Badge></span>
              {:else}
                <Badge tone={scoreTone} dot>{result.estimate_level ?? '—'}</Badge>
              {/if}
            </div>
            <div class="mt-3 flex items-baseline gap-3">
              <span class="nums font-display text-5xl" style:color={scoreTone === 'success' ? 'var(--success)' : scoreTone === 'warn' ? 'var(--warn)' : 'var(--danger)'}>{Math.round(result.score * 100)}</span>
              <span class="text-sm text-muted">/ 100</span>
              {#if result.delta != null}
                <span class="nums ml-auto text-sm" style:color={result.delta >= 0 ? 'var(--success)' : 'var(--danger)'}>
                  <span aria-hidden="true">{result.delta > 0 ? '↑' : '↓'}</span><span class="sr-only">{result.delta > 0 ? 'up' : 'down'}</span> {Math.abs(result.delta).toFixed(2)}
                </span>
              {/if}
            </div>

            {#if artifact}
              <p class="mt-2 text-xs leading-relaxed text-muted">
                Artifact reviews corroborate rather than grade: a score of {Math.round(HELD * 100)}+ lights the
                <span class="text-fg-dim">shipped</span> signal, and a program milestone counts it as artifact
                evidence at {Math.round(MILESTONE_ARTIFACT * 100)}+. The concept's grade is unchanged.
              </p>
            {/if}

            {#if result.confidence_predicted != null}
              <div class="mt-3 flex items-center gap-2 rounded-[var(--radius-sm)] bg-surface-2 px-3 py-2 text-xs">
                <span class="text-muted">predicted</span>
                <span class="nums text-fg">{pct(result.confidence_predicted)}</span>
                <span class="text-faint">vs actual</span>
                <span class="nums text-fg">{pct(result.confidence_actual)}</span>
              </div>
            {/if}

            <p class="mt-3 text-sm leading-relaxed text-fg-dim"><Markdown text={result.verdict} block /></p>

            {#if result.gaps.length}
              <div class="mt-4">
                <span class="eyebrow">gaps</span>
                <ul class="mt-1.5 flex flex-col gap-1">
                  {#each result.gaps as g}<li class="flex items-start gap-2 text-sm text-muted"><span class="shrink-0 text-danger" aria-hidden="true">▸</span><Markdown text={g} class="min-w-0" /></li>{/each}
                </ul>
                <Button variant="outline" size="sm" class="mt-3" onclick={remediate} disabled={remediating}>
                  {remediating ? 'Adding steps…' : 'Add steps to fill these gaps'}
                </Button>
                {#if remediatedCount != null}
                  <p class="mt-2 text-xs text-muted" role="status">
                    {remediatedCount > 0 ? `Added ${remediatedCount} step${remediatedCount === 1 ? '' : 's'} to your track.` : 'A step already on your track covers these.'}
                    <a class="text-accent underline" href="/topics/{topicId}/track">Open track →</a>
                  </p>
                {/if}
              </div>
            {/if}
          </Card>
        {:else}
          <Card pad class="grid h-full min-h-48 place-items-center text-center">
            <p class="text-sm text-faint">Your assessment result will appear here.</p>
          </Card>
        {/if}
      </div>
    </div>
  {/if}
</Page>
