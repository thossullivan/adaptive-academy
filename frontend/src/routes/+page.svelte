<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { topics } from '$lib/topics.svelte';
  import { setup } from '$lib/setup.svelte';
  import { api, scoutCardTitle } from '$lib/api';
  import type { Curriculum, Assessment, EventOut, Concept, TopicSuggestion } from '$lib/types';
  import { conceptSignals, conceptVerdict, VERDICT_RANK, type ConceptSignals, type Verdict } from '$lib/competence';
  import Page from '$lib/shell/Page.svelte';
  import EventFeed from '$lib/shell/EventFeed.svelte';
  import { Card, Button, Badge, Stat, SignalStrip, ProgressRing, ScoutCard, SetupNotice } from '$lib/ui';
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
  let scoutMilestoneTitle = $state('');
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

  async function loadScout(topicId: number) {
    scoutSuggestions = [];
    scoutMilestoneId = null;
    scoutMilestoneTitle = '';
    scoutError = '';
    const context = await api.programContext(topicId).catch(() => null);
    if (!context) return;
    scoutMilestoneId = context.milestone_id;
    scoutMilestoneTitle = context.milestone_title;
    scoutSuggestions = await api
      .listSuggestions(context.program_id, 'proposed')
      .catch(() => [] as TopicSuggestion[]);
  }

  // A topic switch mid-load starts a second load; only the latest one may write state.
  let loadSeq = 0;

  async function load(topicId: number) {
    const seq = ++loadSeq;
    const stale = () => seq !== loadSeq;
    loading = true;
    hasCurriculum = false;
    await loadScout(topicId);
    if (stale()) return;
    let c: Curriculum;
    try {
      c = await api.getCurriculum(topicId);
    } catch {
      if (stale()) return;
      cur = null;
      loading = false;
      return;
    }
    if (stale()) return;
    cur = c;
    hasCurriculum = true;

    // Progress from phases/items.
    let done = 0,
      total = 0;
    phaseProg = c.phases.map((p) => {
      const d = p.items.filter((it) => it.status === 'done').length;
      done += d;
      total += p.items.length;
      return { title: p.title, done: d, total: p.items.length };
    });
    itemsDone = done;
    itemsTotal = total;

    // Per-concept assessments → levels, trend, calibration.
    const assessLists = await Promise.all(
      c.concepts.map((k) => api.listAssessments(k.id).catch(() => [] as Assessment[]))
    );
    if (stale()) return;

    rows = c.concepts.map((k, idx) => {
      const signals = conceptSignals(assessLists[idx]);
      return { ...k, signals, verdict: conceptVerdict(signals), n: assessLists[idx].length };
    });

    const flat: { id: number; a: Assessment; label: string }[] = [];
    c.concepts.forEach((k, idx) => {
      assessLists[idx].forEach((a) => flat.push({ id: a.id, a, label: k.name }));
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
    if (stale()) return;
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

  onMount(() => {
    setup.refresh();
  });

  $effect(() => {
    const id = topics.current?.id;
    if (id != null) load(id);
    else loading = false;
  });

  const tid = $derived(topics.current?.id ?? null);

  // The demo topic: one click to a worked example (no API key), one confirmed click to remove.
  let demoBusy = $state(false);
  let demoError = $state('');
  let confirmRemove = $state(false);
  let removing = $state(false);

  async function exploreDemo() {
    demoBusy = true;
    demoError = '';
    try {
      const { topic_id } = await api.createDemo();
      // Select first: the list then arrives with the demo already current (one dashboard load).
      topics.select(topic_id);
      await topics.refresh();
      await goto('/');
    } catch (e) {
      demoError = `Couldn't load the demo: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      demoBusy = false;
    }
  }

  async function removeDemo() {
    const id = topics.current?.id;
    if (id == null) return;
    removing = true;
    demoError = '';
    try {
      await api.deleteDemo();
      topics.forget(id);
      await topics.refresh();
      confirmRemove = false;
      await goto('/');
    } catch (e) {
      demoError = `Couldn't remove the demo: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      removing = false;
    }
  }

  // First-run entry points: a Program is the long-horizon path, a Topic the single-subject one.
  const entryPoints = [
    {
      href: '/programs/new',
      eyebrow: 'Multi-month goal',
      label: 'Start a program',
      blurb: 'Describe a substantial goal; research drafts a milestone map you review before anything is built.'
    },
    {
      href: '/topics/new',
      eyebrow: 'Single subject',
      label: 'Start a topic',
      blurb: 'Name one subject; the Researcher assembles a foundation you curate, then a phased track.'
    }
  ];
  // Rank concepts: shakiest + load-bearing first — that's where attention belongs.
  const rankedRows = $derived(
    [...rows].sort((a, b) => VERDICT_RANK[a.verdict] - VERDICT_RANK[b.verdict] || Number(b.is_load_bearing) - Number(a.is_load_bearing))
  );
</script>

{#snippet demoBadge()}
  <span data-testid="page-demo-badge"><Badge tone="info" dot>Demo</Badge></span>
{/snippet}

{#if !topics.current}
  <!-- First-run welcome -->
  <div class="grid min-h-[calc(100dvh-3.5rem)] grid-cols-[minmax(0,1fr)] place-items-center px-6 py-10 md:min-h-screen">
    <div class="w-full max-w-2xl text-center rise">
      <div class="mx-auto mb-6 grid size-16 place-items-center rounded-full border border-border bg-surface">
        <svg viewBox="0 0 32 32" class="size-9">
          <circle cx="16" cy="16" r="13" fill="none" stroke="var(--border-strong)" stroke-width="1.5" />
          <circle cx="16" cy="16" r="4.5" fill="var(--accent)" />
        </svg>
      </div>
      <h1 class="text-3xl text-fg">Adaptive Academy</h1>
      <p class="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-muted">
        A private, agent-orchestrated workshop for learning hard things by building. Pick a starting point and
        the Researcher will assemble your foundation.
      </p>

      <SetupNotice status={setup.status} class="mt-7" />

      <div class="mt-7 grid grid-cols-1 gap-3 text-left sm:grid-cols-2">
        {#each entryPoints as e (e.href)}
          <a
            href={e.href}
            class="group flex flex-col gap-2 rounded-[var(--radius-lg)] border border-border bg-surface p-5 shadow-[var(--shadow)] transition-[border-color,background] duration-150 hover:border-[color-mix(in_oklab,var(--accent)_45%,var(--border))] hover:bg-surface-2"
          >
            <span class="eyebrow">{e.eyebrow}</span>
            <span class="font-display text-lg text-fg [overflow-wrap:anywhere] group-hover:text-accent-bright">{e.label} →</span>
            <span class="text-sm leading-relaxed text-muted">{e.blurb}</span>
          </a>
        {/each}
      </div>

      <!-- Secondary: look around a worked example before spending anything. -->
      <div class="mt-6 flex flex-col items-center gap-1 text-sm">
        <button
          type="button"
          onclick={exploreDemo}
          disabled={demoBusy}
          class="rounded-[var(--radius-sm)] px-2 py-1 font-medium text-accent transition-colors hover:text-accent-bright hover:underline disabled:opacity-60"
        >
          {demoBusy ? 'Loading the demo…' : 'Explore a demo topic →'}
        </button>
        <p class="max-w-sm text-xs leading-relaxed text-faint">
          A worked example with a few weeks of activity. Needs no API key, and you can remove it later.
        </p>
        {#if demoError}<p class="text-xs text-danger" role="alert">{demoError}</p>{/if}
      </div>
    </div>
  </div>
{:else}
  <Page eyebrow="Learning command center" title={topics.current.title} width="wide" titleAside={topics.current.is_demo ? demoBadge : undefined}>
    {#snippet actions()}
      <Button variant="outline" href="/topics/{tid}/map">Constellation</Button>
      <Button href="/topics/{tid}/today">Start today's session →</Button>
    {/snippet}

    {#if topics.current.is_demo}
      <Card pad class="mb-4 rise" data-testid="demo-notice">
        <div class="flex flex-wrap items-center gap-x-4 gap-y-3">
          <p class="min-w-0 flex-1 basis-64 text-sm leading-relaxed text-fg-dim">
            <span class="font-medium text-fg">This is a demo topic</span> — example data from a few weeks of use, so you
            can see what each page does. Browsing it needs no API key; running the agents does.
          </p>
          {#if confirmRemove}
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-sm text-fg">Remove the demo topic and everything in it?</span>
              <Button size="sm" variant="danger" onclick={removeDemo} disabled={removing}>
                {removing ? 'Removing…' : 'Yes, remove it'}
              </Button>
              <Button size="sm" variant="ghost" onclick={() => (confirmRemove = false)} disabled={removing}>Cancel</Button>
            </div>
          {:else}
            <Button size="sm" variant="outline" onclick={() => (confirmRemove = true)}>Remove demo</Button>
          {/if}
        </div>
        {#if demoError}<p class="mt-2 text-xs text-danger" role="alert">{demoError}</p>{/if}
      </Card>
    {/if}

    <SetupNotice status={setup.status} class="mb-4" />

    {#if scoutTitle}
      <ScoutCard
        suggestions={scoutSuggestions}
        title={scoutTitle}
        busy={scoutBusy}
        error={scoutError}
        targetLabel={scoutMilestoneTitle}
        class="mb-4 rise"
        onaccept={(id) => resolveScoutSuggestion(id, true)}
        ondismiss={(id) => resolveScoutSuggestion(id, false)}
      />
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
