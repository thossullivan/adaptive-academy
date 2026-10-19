<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { toasts } from '$lib/toast.svelte';
  import { api } from '$lib/api';
  import type { Curriculum, Assessment } from '$lib/types';
  import { pct } from '$lib/utils';
  import { artifactOutcome, HELD } from '$lib/competence';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Field, Select, Textarea, Markdown } from '$lib/ui';

  const topicId = Number($page.params.id);
  let cur = $state<Curriculum | null>(null);
  let conceptId = $state<number | null>(null);
  let kind = $state('self_explanation');
  let response = $state('');
  let confidence = $state(70);
  let result = $state<Assessment | null>(null);
  let busy = $state(false);
  let anchorQuestion = $state<string | null>(null);

  const PROBES: { value: string; label: string; blurb: string }[] = [
    { value: 'self_explanation', label: 'Self-explanation', blurb: 'Explain the concept in your own words.' },
    { value: 'calibration', label: 'Calibration', blurb: 'Predict your confidence, then get graded against reality.' },
    { value: 'artifact_review', label: 'Artifact review', blurb: 'Submit something you built for critique.' },
    { value: 'source_quiz', label: 'Source quiz', blurb: 'Answer a source-grounded question.' }
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
        ? artifact.shipped ? 'success' : 'danger'
        : result.score >= 0.7 ? 'success' : result.score >= 0.4 ? 'warn' : 'danger'
  );
</script>

<Page eyebrow="Assessor" title="Assess understanding" lead="Probes that demand you generate, not recognize — the kind that actually moves the needle." width="normal">
  {#if !cur}
    <Card accent pad class="text-center">
      <div class="py-10">
        <h2 class="text-xl text-fg">No curriculum yet</h2>
        <p class="mx-auto mt-2 max-w-sm text-sm text-muted">Generate a track before assessing.</p>
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
          <div class="grid gap-4 sm:grid-cols-2">
            <Field label="Concept">
              <Select bind:value={conceptId}>
                {#each cur.concepts as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
              </Select>
            </Field>
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
            <Field label="Predicted confidence — {confidence}%">
              <input type="range" min="0" max="100" bind:value={confidence} class="w-full accent-[var(--accent)]" />
            </Field>
          {/if}

          {#if kind === 'source_quiz' && anchorQuestion}
            <div class="rounded-[var(--radius-md)] border border-info/40 bg-[color-mix(in_oklab,var(--info)_8%,transparent)] p-3">
              <span class="eyebrow !text-info">question</span>
              <p class="mt-1 text-sm text-fg">{anchorQuestion}</p>
            </div>
          {/if}

          <Field label="Your response">
            <Textarea bind:value={response} rows={7} placeholder="Explain in your own words — reasoning, mechanisms, edge cases…" />
          </Field>

          <Button onclick={run} disabled={busy || conceptId == null} size="lg" class="self-start">
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
                  {result.delta > 0 ? '↑' : '↓'} {Math.abs(result.delta).toFixed(2)}
                </span>
              {/if}
            </div>

            {#if artifact}
              <p class="mt-2 text-xs leading-relaxed text-muted">
                Artifact reviews corroborate rather than grade: a score of {Math.round(HELD * 100)}+ lights the
                <span class="text-fg-dim">shipped</span> signal; the concept's grade is unchanged.
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
                  {#each result.gaps as g}<li class="flex items-start gap-2 text-sm text-muted"><span class="shrink-0 text-danger">▸</span><Markdown text={g} class="min-w-0" /></li>{/each}
                </ul>
                <Button variant="outline" size="sm" class="mt-3" onclick={remediate} disabled={remediating}>
                  {remediating ? 'Remediating…' : 'Remediate these gaps'}
                </Button>
                {#if remediatedCount != null}
                  <p class="mt-2 text-xs text-muted">
                    {remediatedCount > 0 ? `Injected ${remediatedCount} step(s).` : 'Already covered by an open remediation step.'}
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
