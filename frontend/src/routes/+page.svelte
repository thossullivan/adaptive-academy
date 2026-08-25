<script lang="ts">
  import { topics } from '$lib/topics.svelte';
  import { api, evidenceLabel, groupSuggestionsByKind, scoutCardTitle } from '$lib/api';
  import type { Curriculum, Assessment, EventOut, Concept, TopicSuggestion } from '$lib/types';
  import { conceptSignals, conceptVerdict, VERDICT_RANK, type ConceptSignals, type Verdict } from '$lib/competence';
  import Page from '$lib/shell/Page.svelte';
  import EventFeed from '$lib/shell/EventFeed.svelte';
  import { Card, Button, Badge, Stat, SignalStrip, ProgressRing } from '$lib/ui';
  import ScoreTrend from '$lib/charts/ScoreTrend.svelte';
  import CalibrationPlot from '$lib/charts/CalibrationPlot.svelte';

  type ConceptRow = Concept & { signals: ConceptSignals; verdict: Verdict; n: number };

  let loading = $state(true);
  let hasCurriculum = $state(false);
  let cur = $state<Curriculum | null>(null);
  let rows = $state<ConceptRow[]>([]);
  let trend = $state<{ i: number; score: number; label: string }[]>([]);
  let calibration = $state<{ predicted: number; actual: number; label: string }[]>([]);
  let events = $state<EventOut[]>([]);
  let dueCount = $state(0);
  let cardCount = $state(0);
  let scoutSuggestions = $state<TopicSuggestion[]>([]);
  let scoutMilestoneId = $state<number | null>(null);
  let scoutBusy = $state(false);
  let scoutError = $state('');

  let itemsDone = $state(0);
  let itemsTotal = $state(0);
  let phaseProg = $state<{ title: string; done: number; total: number }[]>([]);

  const overallPct = $derived(itemsTotal ? Math.round((itemsDone / itemsTotal) * 100) : 0);
  const solidCount = $derived(rows.filter((r) => r.verdict === 'solid').length);
  const meanScore = $derived(trend.length ? trend.reduce((a, b) => a + b.score, 0) / trend.length : null);
  // Calibration accuracy: 1 − mean|predicted − actual| across calibration probes.
  const calAccuracy = $derived(
    calibration.length
      ? Math.round((1 - calibration.reduce((a, b) => a + Math.abs(b.predicted - b.actual), 0) / calibration.length) * 100)
      : null
  );
  const lastDelta = $derived(
    trend.length >= 2 ? trend[trend.length - 1].score - trend[trend.length - 2].score : null
  );
  const scoutTitle = $derived(scoutCardTitle(scoutSuggestions));
  const scoutGroups = $derived(groupSuggestionsByKind(scoutSuggestions));

  async function loadScout(topicId: number) {
    scoutSuggestions = [];
    scoutMilestoneId = null;
    scoutError = '';
    const context = await api.programContext(topicId).catch(() => null);
    if (!context) return;
    scoutMilestoneId = context.milestone_id;
    scoutSuggestions = await api
      .listSuggestions(context.program_id, 'proposed')
      .catch(() => [] as TopicSuggestion[]);
  }

  async function load(topicId: number) {
    loading = true;
    hasCurriculum = false;
    await loadScout(topicId);
    try {
      cur = await api.getCurriculum(topicId);
      hasCurriculum = true;
    } catch {
      cur = null;
      loading = false;
      return;
    }

    // Progress from phases/items.
    let done = 0,
      total = 0;
    phaseProg = cur.phases.map((p) => {
      const d = p.items.filter((it) => it.status === 'done').length;
      done += d;
      total += p.items.length;
      return { title: p.title, done: d, total: p.items.length };
    });
    itemsDone = done;
    itemsTotal = total;

    // Per-concept assessments → levels, trend, calibration.
    const assessLists = await Promise.all(
      cur.concepts.map((c) => api.listAssessments(c.id).catch(() => [] as Assessment[]))
    );

    rows = cur.concepts.map((c, idx) => {
      const signals = conceptSignals(assessLists[idx]);
      return { ...c, signals, verdict: conceptVerdict(signals), n: assessLists[idx].length };
    });

    const flat: { id: number; a: Assessment; label: string }[] = [];
    cur.concepts.forEach((c, idx) => {
      assessLists[idx].forEach((a) => flat.push({ id: a.id, a, label: c.name }));
    });
    flat.sort((x, y) => x.id - y.id);
    trend = flat.map((f, i) => ({ i, score: f.a.score, label: f.label }));
    calibration = flat
      .filter((f) => f.a.confidence_predicted != null && f.a.confidence_actual != null)
      .map((f) => ({ predicted: f.a.confidence_predicted!, actual: f.a.confidence_actual!, label: f.label }));

    // Retention + activity.
    const [ret, due, evts] = await Promise.all([
      api.listRetention(topicId).catch(() => ({ cards: [], prompts: [] })),
      api.listRetention(topicId, { due: true }).catch(() => ({ cards: [], prompts: [] })),
      api.listEvents(topicId).catch(() => [] as EventOut[])
    ]);
    cardCount = ret.cards.length;
    dueCount = due.cards.length;
    events = evts;

    loading = false;
  }

  async function resolveScoutSuggestion(suggestionId: number, accept: boolean) {
    if (accept && scoutMilestoneId == null) {
      scoutError = 'Choose a Program milestone from the Program page.';
      return;
    }
    scoutBusy = true;
    scoutError = '';
    try {
      if (accept) {
        await api.acceptSuggestion(suggestionId, scoutMilestoneId!);
      } else {
        await api.dismissSuggestion(suggestionId);
      }
      scoutSuggestions = scoutSuggestions.filter((item) => item.id !== suggestionId);
    } catch (e) {
      scoutError = e instanceof Error ? e.message : String(e);
    }
    scoutBusy = false;
  }

  $effect(() => {
    const id = topics.current?.id;
    if (id != null) load(id);
    else loading = false;
  });

  const tid = $derived(topics.current?.id ?? null);
  // Rank concepts: shakiest + load-bearing first — that's where attention belongs.
  const rankedRows = $derived(
    [...rows].sort((a, b) => VERDICT_RANK[a.verdict] - VERDICT_RANK[b.verdict] || Number(b.is_load_bearing) - Number(a.is_load_bearing))
  );
</script>

{#if !topics.current}
  <!-- First-run welcome -->
  <div class="grid min-h-screen place-items-center px-6">
    <div class="max-w-md text-center rise">
      <div class="mx-auto mb-6 grid size-16 place-items-center rounded-full border border-border bg-surface">
        <svg viewBox="0 0 32 32" class="size-9">
          <circle cx="16" cy="16" r="13" fill="none" stroke="var(--border-strong)" stroke-width="1.5" />
          <circle cx="16" cy="16" r="4.5" fill="var(--accent)" />
        </svg>
      </div>
      <h1 class="text-3xl text-fg">Adaptive Academy</h1>
      <p class="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-muted">
        A private, agent-orchestrated workshop for learning hard things by building. Start with a topic and the
        Researcher will assemble your foundation.
      </p>
      <div class="mt-7">
        <Button href="/topics/new" size="lg">Begin a topic →</Button>
      </div>
    </div>
  </div>
{:else}
  <Page eyebrow="Learning command center" title={topics.current.title} width="wide">
    {#snippet actions()}
      <Button variant="outline" href="/topics/{tid}/map">Constellation</Button>
      <Button href="/topics/{tid}/today">Start today's session →</Button>
    {/snippet}

    {#if scoutTitle}
      <Card accent class="mb-4 rise" eyebrow="Evidence-backed topics" title={scoutTitle}>
        <div class="grid gap-4">
          {#each scoutGroups as group (group.kind)}
            <div>
              <Badge mono tone="neutral">{group.kind.replaceAll('_', ' ')}</Badge>
              <ul class="mt-2 grid gap-3">
                {#each group.suggestions as suggestion (suggestion.id)}
                  <li class="flex flex-wrap items-start justify-between gap-3 border-t border-border/50 pt-3 text-sm">
                    <div class="min-w-0 flex-1">
                      <p class="font-medium text-fg">{suggestion.title}</p>
                      <p class="mt-1 text-muted">{suggestion.rationale}</p>
                      <details class="mt-2 text-xs text-faint">
                        <summary class="cursor-pointer">Evidence ({suggestion.evidence.length})</summary>
                        <ul class="mt-1 grid gap-1 pl-3">
                          {#each suggestion.evidence as evidence}
                            <li>{evidenceLabel(evidence)}</li>
                          {/each}
                        </ul>
                      </details>
                    </div>
                    <div class="flex shrink-0 gap-2">
                      <Button
                        size="sm"
                        onclick={() => resolveScoutSuggestion(suggestion.id, true)}
                        disabled={scoutBusy}
                      >Accept</Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onclick={() => resolveScoutSuggestion(suggestion.id, false)}
                        disabled={scoutBusy}
                      >Dismiss</Button>
                    </div>
                  </li>
                {/each}
              </ul>
            </div>
          {/each}
        </div>
        {#if scoutError}<p class="mt-3 text-sm text-danger">{scoutError}</p>{/if}
      </Card>
    {/if}

    {#if loading}
      <div class="grid place-items-center py-24 text-muted">
        <span class="eyebrow animate-pulse">gathering signals…</span>
      </div>
    {:else if !hasCurriculum}
      <Card accent class="text-center" pad>
        <div class="py-10">
          <h2 class="text-xl text-fg">No curriculum yet</h2>
          <p class="mx-auto mt-2 max-w-sm text-sm text-muted">
            Review your reading list and generate a phased track to start measuring progress.
          </p>
          <div class="mt-6"><Button href="/topics/{tid}/review">Go to Sources →</Button></div>
        </div>
      </Card>
    {:else}
      <!-- Stat strip -->
      <div class="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card class="rise" pad><Stat label="Track progress" value={overallPct} unit="%" hint="{itemsDone} of {itemsTotal} steps" /></Card>
        <Card class="rise" pad style="animation-delay:60ms"><Stat label="Concepts solid" value={solidCount} unit="/ {rows.length}" hint="triangulated, not just graded" /></Card>
        <Card class="rise" pad style="animation-delay:120ms"><Stat label="Due for review" value={dueCount} hint="{cardCount} cards total" /></Card>
        <Card class="rise" pad style="animation-delay:180ms"><Stat label="Mean score" value={meanScore == null ? '—' : Math.round(meanScore * 100)} unit={meanScore == null ? '' : '%'} delta={lastDelta == null ? null : Number(lastDelta.toFixed(2))} hint="across {trend.length} probes" /></Card>
      </div>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <!-- Knowledge map -->
        <Card class="rise lg:col-span-2" eyebrow="Knowledge map" title="Where you stand">
          {#snippet header()}
            <span class="text-xs text-faint">◆ grade · ↺ held · ◷ calibrated · ◳ taught · ⚒ shipped</span>
          {/snippet}
          {#if rankedRows.length}
            <p class="mb-2 text-xs text-faint">Competence is <i>triangulated</i>, not graded — a concept reads "solid" only when independent signals agree. <span class="text-fg-dim">Click any concept for why.</span></p>
            <div class="flex flex-col">
              {#each rankedRows as r (r.id)}
                <SignalStrip name={r.name} signals={r.signals} verdict={r.verdict} loadBearing={r.is_load_bearing} hasAnchor={r.has_anchor} />
              {/each}
            </div>
          {:else}
            <p class="py-8 text-center text-sm text-faint">This track has no tracked concepts. Assess one to populate the map.</p>
          {/if}
        </Card>

        <!-- Calibration -->
        <Card class="rise" eyebrow="Metacognition" title="Calibration">
          {#snippet header()}
            {#if calAccuracy != null}
              <span class="nums text-sm" style:color={calAccuracy >= 80 ? 'var(--success)' : calAccuracy >= 60 ? 'var(--accent)' : 'var(--danger)'}>{calAccuracy}% accurate</span>
            {/if}
          {/snippet}
          <CalibrationPlot data={calibration} />
        </Card>

        <!-- Score trajectory -->
        <Card class="rise lg:col-span-2" eyebrow="Assessment history" title="Score trajectory">
          <ScoreTrend data={trend} />
        </Card>

        <!-- Phase progress -->
        <Card class="rise" eyebrow="Phases" title="Build progress">
          <div class="flex flex-col items-center gap-4">
            <ProgressRing value={itemsTotal ? itemsDone / itemsTotal : 0} size={92} stroke={8} label="{overallPct}%" sublabel="complete" />
            <ul class="w-full flex-col gap-1.5">
              {#each phaseProg as p, i}
                <li class="flex items-center gap-2 py-0.5 text-xs">
                  <span class="nums w-4 text-faint">{i + 1}</span>
                  <span class="flex-1 truncate text-fg-dim">{p.title}</span>
                  <span class="nums text-muted">{p.done}/{p.total}</span>
                </li>
              {/each}
            </ul>
          </div>
        </Card>

        <!-- Activity -->
        <Card class="rise lg:col-span-3" eyebrow="Observability" title="Recent agent activity">
          {#snippet header()}
            <Badge mono tone="neutral">{events.length} events</Badge>
          {/snippet}
          <EventFeed {events} limit={12} />
        </Card>
      </div>
    {/if}
  </Page>
{/if}
