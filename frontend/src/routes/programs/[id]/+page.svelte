<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api, evidenceLabel, groupSuggestionsByKind, scoutCardTitle } from '$lib/api';
  import { changeSummary, gateBadge } from '$lib/programs';
  import type {
    GateReport,
    MapRevisionInfo,
    MilestoneInfo,
    ProgramDetail,
    TopicSuggestion
  } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Input, Select, Textarea } from '$lib/ui';

  const programId = Number($page.params.id);
  let detail = $state<ProgramDetail | null>(null);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let pruned = $state<Set<number>>(new Set());
  let gates = $state<Record<number, GateReport>>({});
  let overrideFor = $state<number | null>(null);
  let overrideReason = $state('');
  let probeFor = $state<number | null>(null);
  let probeUrl = $state('');
  let probePaste = $state('');
  let probeTitle = $state('');
  let pendingSave: Promise<unknown> | null = null;
  let revision = $state<MapRevisionInfo | null>(null);
  let showArchived = $state(false);
  let suggestions = $state<TopicSuggestion[]>([]);
  let suggestionMilestones = $state<Record<number, number>>({});
  let scoutNote = $state('');

  const inReview = $derived(
    detail?.milestones.some((m) => m.links.some((l) => l.status === 'proposed')) ?? false
  );
  const scoutGroups = $derived(groupSuggestionsByKind(suggestions));
  const scoutTitle = $derived(scoutCardTitle(suggestions) ?? 'Scout');

  async function load() {
    try {
      const [nextDetail, nextSuggestions] = await Promise.all([
        api.getProgram(programId),
        api.listSuggestions(programId, 'proposed')
      ]);
      detail = nextDetail;
      suggestions = nextSuggestions;
      const firstMilestone = detail.milestones.find((milestone) => !milestone.archived);
      const nextChoices = { ...suggestionMilestones };
      for (const suggestion of suggestions) {
        if (nextChoices[suggestion.id] == null && firstMilestone) {
          nextChoices[suggestion.id] = firstMilestone.id;
        }
      }
      suggestionMilestones = nextChoices;
      revision = detail?.has_open_revision ? await api.getOpenRevision(programId).catch(() => null) : null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  async function runScout() {
    busy = true;
    error = '';
    scoutNote = '';
    try {
      const result = await api.runScout(programId);
      const count = Object.values(result.candidates).reduce((total, value) => total + value, 0);
      scoutNote = `Scout reviewed ${count} candidate${count === 1 ? '' : 's'}${
        result.truncated ? ' within its time limit' : ''
      }.`;
      suggestions = await api.listSuggestions(programId, 'proposed');
      const firstMilestone = detail?.milestones.find((milestone) => !milestone.archived);
      if (firstMilestone) {
        const nextChoices = { ...suggestionMilestones };
        for (const suggestion of suggestions) {
          nextChoices[suggestion.id] ??= firstMilestone.id;
        }
        suggestionMilestones = nextChoices;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    busy = false;
  }

  async function resolveSuggestion(suggestionId: number, accept: boolean) {
    const milestoneId = suggestionMilestones[suggestionId];
    if (accept && milestoneId == null) {
      error = 'Select a milestone before accepting this suggestion.';
      return;
    }
    busy = true;
    error = '';
    try {
      if (accept) {
        await api.acceptSuggestion(suggestionId, milestoneId);
        detail = await api.getProgram(programId);
      } else {
        await api.dismissSuggestion(suggestionId);
      }
      suggestions = suggestions.filter((suggestion) => suggestion.id !== suggestionId);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    busy = false;
  }

  async function revise() {
    busy = true;
    error = '';
    try {
      revision = await api.reviseMap(programId);
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    busy = false;
  }

  async function resolveChange(changeId: number, accept: boolean) {
    busy = true;
    error = '';
    try {
      detail = accept
        ? await api.acceptChange(programId, changeId)
        : await api.rejectChange(programId, changeId);
      revision = detail.has_open_revision
        ? await api.getOpenRevision(programId).catch(() => null)
        : null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    busy = false;
  }

  async function runResearch() {
    busy = true;
    error = '';
    try {
      detail = await api.programResearch(programId);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    busy = false;
  }

  function togglePrune(id: number) {
    const next = new Set(pruned);
    next.has(id) ? next.delete(id) : next.add(id);
    pruned = next;
  }

  async function accept() {
    if (!detail) return;
    busy = true;
    error = '';
    if (pendingSave) {
      try {
        await pendingSave;
      } catch {
        /* already surfaced by saveMilestone */
      }
      pendingSave = null;
    }
    const all = detail.milestones.flatMap((m) => m.links.filter((l) => l.status === 'proposed'));
    const prunedIds = all.filter((l) => pruned.has(l.id)).map((l) => l.id);
    const keptIds = all.filter((l) => !pruned.has(l.id)).map((l) => l.id);
    try {
      detail = await api.acceptProgram(programId, keptIds, prunedIds);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    busy = false;
  }

  async function saveMilestone(m: MilestoneInfo) {
    error = '';
    const save = api.updateMilestone(programId, m.id, {
      title: m.title,
      success_criteria: m.success_criteria
    });
    // Chain onto any in-flight save so accept() can await them all.
    pendingSave = pendingSave ? Promise.allSettled([pendingSave, save]) : save;
    try {
      await save;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  async function start(linkId: number) {
    busy = true;
    error = '';
    try {
      const { topic_id } = await api.startLink(programId, linkId);
      await goto(`/topics/${topic_id}/review`);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      busy = false;
    }
  }

  async function loadGate(m: MilestoneInfo) {
    busy = true;
    error = '';
    try {
      gates = { ...gates, [m.id]: await api.milestoneGate(programId, m.id) };
      await load(); // gate evaluation can update stored gate_status
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    busy = false;
  }

  async function confirmOverride(mid: number) {
    if (!overrideReason.trim()) {
      error = 'Override requires a reason.';
      return;
    }
    busy = true;
    error = '';
    try {
      await api.overrideGate(programId, mid, overrideReason.trim());
      overrideFor = null;
      overrideReason = '';
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    busy = false;
  }

  function startedTopic(m: MilestoneInfo) {
    return m.links.find((l) => l.status === 'started');
  }

  async function spar(m: MilestoneInfo) {
    busy = true;
    error = '';
    try {
      const session = await api.startRoleplay(programId, m.id);
      await goto(`/roleplay/${session.session_id}`);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      busy = false;
    }
  }

  async function startProbe(m: MilestoneInfo) {
    if (!probeUrl.trim() && !probePaste.trim()) {
      error = 'Give an arXiv URL or paste the paper text.';
      return;
    }
    busy = true;
    error = '';
    try {
      const probe = await api.startPaperProbe(programId, m.id, {
        url: probeUrl.trim(),
        pasted_text: probePaste.trim(),
        title: probeTitle.trim()
      });
      await goto(`/paper-probe/${probe.probe_id}`);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      busy = false;
    }
  }
</script>

<svelte:head><title>{detail?.program.title ?? 'Program'} · Adaptive Academy</title></svelte:head>

<Page
  eyebrow="Program"
  title={detail?.program.title ?? ''}
  width="wide"
  lead={detail?.program.goal_statement ?? ''}
>
  {#snippet actions()}
    {#if detail && detail.milestones.length > 0}
      <Button onclick={revise} disabled={busy || inReview || detail.has_open_revision}
        >Revise map</Button
      >
    {/if}
  {/snippet}

  {#if loading}
    <p class="text-sm text-muted">Loading…</p>
  {:else if !detail}
    <p class="text-sm text-danger">Couldn’t load program: {error}</p>
  {:else if detail.milestones.length === 0}
    <Card>
      <p class="mb-4 text-sm text-muted">
        No milestone map yet. Research surveys real PhD curricula, quals syllabi, canonical
        courses, and reading lists, then drafts milestones + topic candidates for your review.
      </p>
      <Button onclick={runResearch} disabled={busy}>{busy ? 'Researching…' : 'Run research'}</Button
      >
      {#if error}<p class="mt-3 text-sm text-danger">{error}</p>{/if}
    </Card>
  {:else}
    {#if inReview}
      <Card>
        <div class="flex items-center justify-between gap-3">
          <p class="text-sm text-muted">
            Proposal under review — edit titles/criteria inline, uncheck any candidate topic to
            prune it, then accept.
          </p>
          <Button onclick={accept} disabled={busy}>{busy ? 'Accepting…' : 'Accept program'}</Button>
        </div>
        {#if error}<p class="mt-2 text-sm text-danger">{error}</p>{/if}
      </Card>
    {/if}
    {#if !inReview && error}<p class="mt-3 text-sm text-danger">{error}</p>{/if}

    {#if detail.revision_suggested && !detail.has_open_revision}
      <Card class="mt-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <p class="text-sm text-muted">Leg verified — revise the map with what you've learned?</p>
          <Button onclick={revise} disabled={busy}>Revise map</Button>
        </div>
      </Card>
    {/if}

    {#if revision}
      <Card class="mt-4">
        <div class="eyebrow mb-2">Map revision</div>
        <p class="mb-4 text-sm text-muted">{revision.map_health}</p>
        <ul class="grid gap-3">
          {#each revision.changes.filter((c) => c.status === 'proposed') as c (c.id)}
            <li class="flex flex-wrap items-start justify-between gap-3 text-sm">
              <div class="min-w-0">
                <div class="text-fg">{changeSummary(c)}</div>
                <p class="mt-1 text-muted">{c.why}</p>
                {#if c.source_urls.length > 0}
                  <p class="mt-1 truncate text-xs text-muted">
                    {#each c.source_urls.slice(0, 2) as u (u)}
                      <a class="text-accent hover:underline" href={u} target="_blank" rel="noreferrer"
                        >{u}</a
                      >&nbsp;
                    {/each}
                  </p>
                {/if}
              </div>
              <div class="flex shrink-0 gap-2">
                <Button onclick={() => resolveChange(c.id, true)} disabled={busy}>Accept</Button>
                <button
                  class="text-sm text-muted hover:text-fg"
                  onclick={() => resolveChange(c.id, false)}
                  disabled={busy}
                >
                  Reject
                </button>
              </div>
            </li>
          {/each}
        </ul>
      </Card>
    {/if}

    {@const milestones = detail.milestones}
    {@const visibleMilestones = milestones.filter((m) => showArchived || !m.archived)}
    {@const archivedCount = milestones.filter((m) => m.archived).length}
    <div class="mt-4 grid gap-4">
      {#each visibleMilestones as m, i (m.id)}
        {@const depRefs = m.depends_on
          .map((d) => visibleMilestones.findIndex((x) => x.id === d))
          .filter((pos) => pos >= 0)
          .map((pos) => `#${pos + 1}`)}
        <Card class={m.archived ? 'opacity-60' : ''}>
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="eyebrow">
                Leg {i + 1}{depRefs.length ? ` · after ${depRefs.join(', ')}` : ''}
              </div>
              {#if inReview}
                <div class="mt-2 grid max-w-xl gap-2">
                  <Input bind:value={m.title} onblur={() => saveMilestone(m)} />
                  <Textarea
                    bind:value={m.success_criteria}
                    rows={2}
                    onblur={() => saveMilestone(m)}
                  />
                </div>
              {:else}
                <h2 class="mt-1 text-lg text-fg">{m.title}</h2>
                <p class="mt-1 text-sm text-muted">{m.success_criteria}</p>
              {/if}
              {#if m.gate_status === 'overridden' && m.override_reason}
                <p class="mt-1 text-xs text-muted">Override reason: {m.override_reason}</p>
              {/if}
            </div>
            <div class="flex shrink-0 items-center gap-2">
              {#if m.archived}<Badge>Archived</Badge>{/if}
              <Badge tone={gateBadge(m.gate_status).tone}>{gateBadge(m.gate_status).label}</Badge>
            </div>
          </div>

          <ul class="mt-4 grid gap-2">
            {#each m.links as l (l.id)}
              <li class="flex items-start justify-between gap-3 text-sm">
                <div class="flex min-w-0 flex-1 items-start gap-2">
                  {#if l.status === 'proposed'}
                    <input
                      type="checkbox"
                      class="mt-1 shrink-0"
                      checked={!pruned.has(l.id)}
                      onchange={() => togglePrune(l.id)}
                    />
                  {/if}
                  <div class="min-w-0">
                    <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span class={l.status === 'pruned' ? 'text-muted line-through' : 'text-fg'}>
                        {l.proposed_title}
                      </span>
                      {#if l.added_by === 'revision'}<Badge tone="accent">revision</Badge>{/if}
                    </div>
                    {#if l.why}<p class="mt-0.5 text-muted">{l.why}</p>{/if}
                  </div>
                </div>
                <div class="flex shrink-0 items-center gap-2">
                  {#if l.status === 'stub'}
                    <Button onclick={() => start(l.id)} disabled={busy}>Start topic</Button>
                  {:else if l.status === 'started' && l.topic_id}
                    <a class="text-accent hover:underline" href={`/topics/${l.topic_id}/today`}
                      >Open topic</a
                    >
                  {:else}
                    <Badge>{l.status}</Badge>
                  {/if}
                </div>
              </li>
            {/each}
          </ul>

          {#if !inReview}
            <div class="mt-4 flex items-center gap-3">
              <Button size="sm" onclick={() => loadGate(m)} disabled={busy}>Check gate</Button>
              <Button
                size="sm"
                variant="outline"
                onclick={() => spar(m)}
                disabled={busy || !startedTopic(m)}
                title={startedTopic(m) ? '' : "Start this milestone's topic first."}
              >
                Spar
              </Button>
              <Button
                size="sm"
                variant="outline"
                onclick={() => {
                  probeFor = probeFor === m.id ? null : m.id;
                  probeUrl = '';
                  probePaste = '';
                  probeTitle = '';
                }}
                disabled={busy || !startedTopic(m)}
                title={startedTopic(m) ? '' : "Start this milestone's topic first."}
              >
                Probe a paper
              </Button>
              {#if m.gate_status !== 'passed' && overrideFor !== m.id}
                <button
                  class="text-sm text-muted hover:text-fg"
                  onclick={() => {
                    overrideFor = m.id;
                    overrideReason = '';
                  }}
                >
                  Override…
                </button>
              {/if}
            </div>
            {#if probeFor === m.id}
              <div class="mt-3 flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3">
                <input
                  bind:value={probeUrl}
                  placeholder="arXiv URL (e.g. https://arxiv.org/abs/1706.03762)"
                  class="rounded-[var(--radius-sm)] border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none"
                />
                <div class="text-center text-xs text-muted">or</div>
                <textarea
                  bind:value={probePaste}
                  rows="3"
                  placeholder="Paste the paper text…"
                  class="resize-y rounded-[var(--radius-sm)] border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none"
                ></textarea>
                <input
                  bind:value={probeTitle}
                  placeholder="Title (optional)"
                  class="rounded-[var(--radius-sm)] border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none"
                />
                <div>
                  <Button size="sm" onclick={() => startProbe(m)} disabled={busy}>Start probe</Button>
                </div>
              </div>
            {/if}
            {#if overrideFor === m.id}
              <div class="mt-3 grid gap-2">
                <Textarea
                  bind:value={overrideReason}
                  rows={2}
                  placeholder="Why are you moving on without verification? (logged permanently)"
                />
                <div class="flex gap-2">
                  <Button size="sm" onclick={() => confirmOverride(m.id)} disabled={busy}
                    >Confirm override</Button
                  >
                  <button class="text-sm text-muted" onclick={() => (overrideFor = null)}
                    >Cancel</button
                  >
                </div>
              </div>
            {/if}
            {#if gates[m.id]}
              <div class="mt-4 overflow-x-auto">
                <p class="mb-2 text-xs text-muted">{gates[m.id].reason}</p>
                {#if gates[m.id].concepts.length > 0}
                  <table class="w-full text-sm">
                    <thead>
                      <tr class="text-left text-xs text-muted">
                        <th class="py-1 pr-4 font-normal">Load-bearing concept</th>
                        <th class="py-1 pr-4 font-normal">Delayed recall</th>
                        <th class="py-1 pr-4 font-normal">Artifact</th>
                        <th class="py-1 font-normal">Verdict</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each gates[m.id].concepts as c (c.concept_id)}
                        <tr class="border-t border-border/50">
                          <td class="py-1.5 pr-4 text-fg">{c.name}</td>
                          <td class="py-1.5 pr-4">{c.delayed_ok ? '✓' : '—'}</td>
                          <td class="py-1.5 pr-4">{c.artifact_ok ? '✓' : '—'}</td>
                          <td class="py-1.5"
                            ><Badge tone={gateBadge(c.verdict).tone}
                              >{gateBadge(c.verdict).label}</Badge
                            ></td
                          >
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                {/if}
              </div>
            {/if}
          {/if}
        </Card>
      {/each}
    </div>
    {#if archivedCount > 0}
      <button
        class="mt-3 text-xs text-muted hover:text-fg"
        onclick={() => (showArchived = !showArchived)}
      >
        {showArchived ? 'Hide archived' : `Show ${archivedCount} archived`}
      </button>
    {/if}

    <Card accent class="mt-4" eyebrow="Evidence-backed topics" title={scoutTitle}>
      {#snippet header()}
        <Button size="sm" onclick={runScout} disabled={busy}
          >{busy ? 'Running…' : 'Run scout'}</Button
        >
      {/snippet}
      {#if scoutNote}<p class="mb-3 text-xs text-muted">{scoutNote}</p>{/if}
      {#if scoutGroups.length === 0}
        <p class="text-sm text-muted">No proposed suggestions.</p>
      {:else}
        <div class="grid gap-5">
          {#each scoutGroups as group (group.kind)}
            <div>
              <Badge mono tone="neutral">{group.kind.replaceAll('_', ' ')}</Badge>
              <ul class="mt-2 grid gap-3">
                {#each group.suggestions as suggestion (suggestion.id)}
                  <li class="grid gap-3 border-t border-border/50 pt-3 text-sm lg:grid-cols-[minmax(0,1fr)_minmax(12rem,18rem)]">
                    <div class="min-w-0">
                      <div class="flex flex-wrap items-baseline gap-2">
                        <p class="font-medium text-fg">{suggestion.title}</p>
                        <span class="nums text-xs text-faint"
                          >{Math.round(suggestion.score * 100)}%</span
                        >
                      </div>
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
                    <div class="grid content-start gap-2">
                      <Select bind:value={suggestionMilestones[suggestion.id]} disabled={busy}>
                        {#each detail.milestones.filter((milestone) => !milestone.archived) as milestone (milestone.id)}
                          <option value={milestone.id}>{milestone.title}</option>
                        {/each}
                      </Select>
                      <div class="flex gap-2">
                        <Button
                          size="sm"
                          onclick={() => resolveSuggestion(suggestion.id, true)}
                          disabled={busy}
                        >Accept</Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onclick={() => resolveSuggestion(suggestion.id, false)}
                          disabled={busy}
                        >Dismiss</Button>
                      </div>
                    </div>
                  </li>
                {/each}
              </ul>
            </div>
          {/each}
        </div>
      {/if}
    </Card>
  {/if}
</Page>
