<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Concept, Assessment, Consolidation } from '$lib/types';
  import { pct } from '$lib/utils';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Field, Select, Textarea, Markdown } from '$lib/ui';

  const topicId = Number($page.params.id);
  let concepts = $state<Concept[]>([]);
  let conceptId = $state<number | null>(null);
  let tab = $state<'pf' | 'cal'>('pf');

  onMount(async () => {
    try {
      const cur = await api.getCurriculum(topicId);
      concepts = cur.concepts;
      conceptId = cur.concepts[0]?.id ?? null;
    } catch {
      concepts = [];
    }
  });

  const conceptName = $derived(concepts.find((c) => c.id === conceptId)?.name ?? '');

  // ── Productive Failure ──────────────────────────────────────────────
  let problem = $state('');
  let attempt = $state('');
  let consolidation = $state<Consolidation | null>(null);
  let generating = $state(false);
  let consolidating = $state(false);

  async function generate() {
    if (conceptId == null) return;
    generating = true;
    problem = '';
    attempt = '';
    consolidation = null;
    try {
      problem = (await api.generateChallenge(conceptId)).problem;
    } finally {
      generating = false;
    }
  }

  async function reveal() {
    if (conceptId == null || !attempt.trim()) return;
    consolidating = true;
    try {
      consolidation = await api.consolidate(conceptId, problem, attempt);
    } finally {
      consolidating = false;
    }
  }

  // ── Calibration Loop ────────────────────────────────────────────────
  let calPhase = $state<'predict' | 'explain' | 'result'>('predict');
  let confidence = $state(70);
  let explanation = $state('');
  let calResult = $state<Assessment | null>(null);
  let submitting = $state(false);
  let calAccuracy = $state<number | null>(null);

  async function loadCalAccuracy() {
    if (conceptId == null) return;
    const list = await api.listAssessments(conceptId).catch(() => [] as Assessment[]);
    const cal = list.filter((a) => a.confidence_predicted != null && a.confidence_actual != null);
    calAccuracy = cal.length
      ? Math.round((1 - cal.reduce((s, a) => s + Math.abs((a.confidence_predicted ?? 0) - (a.confidence_actual ?? 0)), 0) / cal.length) * 100)
      : null;
  }

  $effect(() => {
    conceptId;
    resetCal();
    loadCalAccuracy();
  });

  function resetCal() {
    calPhase = 'predict';
    explanation = '';
    calResult = null;
  }

  async function submitCal() {
    if (conceptId == null) return;
    submitting = true;
    try {
      calResult = await api.assess(conceptId, {
        kind: 'calibration',
        response: explanation,
        confidence_predicted: confidence / 100
      });
      calPhase = 'result';
      await loadCalAccuracy();
    } finally {
      submitting = false;
    }
  }

  const calGap = $derived(
    calResult && calResult.confidence_predicted != null && calResult.confidence_actual != null
      ? Math.round((calResult.confidence_predicted - calResult.confidence_actual) * 100)
      : null
  );
</script>

<Page eyebrow="Generative practice" title="Practice" lead="The work that actually solidifies understanding — struggle before you're shown, and confront what you only thought you knew." width="normal">
  {#snippet actions()}
    <Field label="">
      <Select bind:value={conceptId} class="w-56">
        {#each concepts as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
      </Select>
    </Field>
  {/snippet}

  {#if !concepts.length}
    <Card pad class="text-center"><p class="py-8 text-sm text-muted">No concepts to practice yet — generate a curriculum first.</p></Card>
  {:else}
    <!-- Tabs -->
    <div class="mb-4 flex gap-1 rounded-[var(--radius-md)] border border-border bg-surface-2 p-1">
      <button
        class="flex-1 rounded-[var(--radius-sm)] px-3 py-2 text-sm font-medium transition-colors {tab === 'pf' ? 'bg-surface text-fg shadow-[var(--shadow)]' : 'text-muted hover:text-fg'}"
        onclick={() => (tab = 'pf')}
      >◈ Productive Failure</button>
      <button
        class="flex-1 rounded-[var(--radius-sm)] px-3 py-2 text-sm font-medium transition-colors {tab === 'cal' ? 'bg-surface text-fg shadow-[var(--shadow)]' : 'text-muted hover:text-fg'}"
        onclick={() => (tab = 'cal')}
      >◷ Calibration</button>
    </div>

    {#if tab === 'pf'}
      <div class="flex flex-col gap-4">
        <Card pad>
          <div class="flex items-center justify-between gap-3">
            <div>
              <span class="eyebrow">grapple first</span>
              <p class="mt-1 text-sm text-muted">Generate a novel problem on <b class="text-fg-dim">{conceptName}</b> and attempt it <i>before</i> any method is shown. Failing productively is the point.</p>
            </div>
            <Button onclick={generate} disabled={generating || conceptId == null}>{generating ? 'Generating…' : problem ? 'New challenge' : 'Generate challenge'}</Button>
          </div>
        </Card>

        {#if problem}
          <Card accent pad class="rise">
            <span class="eyebrow text-accent">the problem</span>
            <p class="mt-2 text-[0.95rem] leading-relaxed text-fg"><Markdown text={problem} block /></p>
          </Card>

          {#if !consolidation}
            <Card pad class="rise">
              <Field label="Your attempt — reason it out, even if you don't reach the answer">
                <Textarea bind:value={attempt} rows={7} placeholder="Here's how I'd approach it…" />
              </Field>
              <p class="mt-2 text-xs text-faint">The canonical method stays hidden until you commit an attempt.</p>
              <Button class="mt-3" onclick={reveal} disabled={consolidating || !attempt.trim()}>{consolidating ? 'Consolidating…' : 'Commit & reveal →'}</Button>
            </Card>
          {:else}
            <Card pad class="rise">
              <span class="eyebrow">your attempt</span>
              <p class="mt-1 whitespace-pre-wrap text-sm text-muted">{attempt}</p>
            </Card>
            <Card accent pad class="rise">
              <div class="flex items-center justify-between">
                <span class="eyebrow text-accent">consolidation</span>
                <Badge tone={consolidation.score >= 0.6 ? 'success' : 'accent'} dot>effort {Math.round(consolidation.score * 100)}%</Badge>
              </div>
              <p class="mt-3 text-sm leading-relaxed text-fg-dim"><Markdown text={consolidation.feedback} block /></p>
              <div class="mt-4 border-t border-border pt-3">
                <span class="eyebrow">canonical approach</span>
                <p class="mt-1.5 text-sm leading-relaxed text-fg"><Markdown text={consolidation.canonical} block /></p>
              </div>
            </Card>
          {/if}
        {/if}
      </div>
    {:else}
      <!-- Calibration loop -->
      <div class="flex flex-col gap-4">
        <Card pad>
          <div class="flex items-center justify-between">
            <div>
              <span class="eyebrow">metacognition</span>
              <p class="mt-1 text-sm text-muted">Predict, then explain <b class="text-fg-dim">{conceptName}</b> — we measure the gap between how well you <i>think</i> you know it and how well you do.</p>
            </div>
            {#if calAccuracy != null}
              <div class="text-right">
                <div class="nums font-display text-2xl" style:color={calAccuracy >= 80 ? 'var(--success)' : calAccuracy >= 60 ? 'var(--accent)' : 'var(--danger)'}>{calAccuracy}%</div>
                <div class="eyebrow !text-[0.55rem]">calibration accuracy</div>
              </div>
            {/if}
          </div>
        </Card>

        {#if calPhase === 'predict'}
          <Card accent pad class="rise">
            <span class="eyebrow text-accent">step 1 · predict</span>
            <p class="mt-2 text-sm text-muted">Before you explain anything: how well do you think you understand {conceptName}?</p>
            <div class="mt-4">
              <div class="mb-1 flex justify-between text-sm"><span class="text-muted">not at all</span><span class="nums font-display text-2xl text-fg">{confidence}%</span><span class="text-muted">cold</span></div>
              <input type="range" min="0" max="100" bind:value={confidence} class="w-full accent-[var(--accent)]" />
            </div>
            <Button class="mt-4" onclick={() => (calPhase = 'explain')}>Lock prediction →</Button>
          </Card>
        {:else if calPhase === 'explain'}
          <Card pad class="rise">
            <div class="flex items-center justify-between">
              <span class="eyebrow">step 2 · explicate</span>
              <Badge tone="neutral" mono>predicted {confidence}%</Badge>
            </div>
            <p class="mt-2 text-sm font-medium text-fg">Explain why {conceptName} works — the mechanism, in your own words.</p>
            <Textarea class="mt-3" bind:value={explanation} rows={7} placeholder="It works because…" />
            <Button class="mt-3" onclick={submitCal} disabled={submitting}>{submitting ? 'Grading…' : 'Submit & confront the gap →'}</Button>
          </Card>
        {:else if calResult}
          <Card accent pad class="rise">
            <span class="eyebrow text-accent">the reckoning</span>
            <div class="mt-3 grid grid-cols-2 gap-4">
              <div class="text-center">
                <div class="eyebrow">you predicted</div>
                <div class="nums font-display text-4xl text-muted">{pct(calResult.confidence_predicted)}</div>
              </div>
              <div class="text-center">
                <div class="eyebrow">you actually scored</div>
                <div class="nums font-display text-4xl" style:color={(calResult.confidence_actual ?? 0) >= (calResult.confidence_predicted ?? 0) ? 'var(--success)' : 'var(--danger)'}>{pct(calResult.confidence_actual)}</div>
              </div>
            </div>
            {#if calGap != null}
              <div class="mt-4 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3 text-center text-sm">
                {#if Math.abs(calGap) <= 10}
                  <span class="text-success">Well calibrated — your self-assessment matched reality.</span>
                {:else if calGap > 0}
                  <span class="text-danger">Overconfident by {calGap} points</span> <span class="text-muted">— the illusion of competence. You knew it less well than you felt.</span>
                {:else}
                  <span class="text-info">Underconfident by {Math.abs(calGap)} points</span> <span class="text-muted">— you know more than you give yourself credit for.</span>
                {/if}
              </div>
            {/if}
            <p class="mt-3 text-sm leading-relaxed text-fg-dim">{calResult.verdict}</p>
            <Button variant="outline" class="mt-4" onclick={resetCal}>Run another →</Button>
          </Card>
        {/if}
      </div>
    {/if}
  {/if}
</Page>
