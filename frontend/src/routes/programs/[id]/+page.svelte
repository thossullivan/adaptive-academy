<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { changeSummary, gateBadge } from '$lib/programs';
  import type { GateReport, MapRevisionInfo, MilestoneInfo, ProgramDetail } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Input, Textarea } from '$lib/ui';

  const programId = Number($page.params.id);
  let detail = $state<ProgramDetail | null>(null);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let pruned = $state<Set<number>>(new Set());
  let gates = $state<Record<number, GateReport>>({});
  let overrideFor = $state<number | null>(null);
  let overrideReason = $state('');
  let pendingSave: Promise<unknown> | null = null;
  let revision = $state<MapRevisionInfo | null>(null);
  let showArchived = $state(false);

  const inReview = $derived(
    detail?.milestones.some((m) => m.links.some((l) => l.status === 'proposed')) ?? false
  );

  async function load() {
    try {
      detail = await api.getProgram(programId);
      revision = detail?.has_open_revision ? await api.getOpenRevision(programId).catch(() => null) : null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

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
      <Button onclick={revise} disabled={busy || detail.has_open_revision}>Revise map</Button>
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
              <li class="flex items-center justify-between gap-3 text-sm">
                <div class="flex min-w-0 items-center gap-2">
                  {#if l.status === 'proposed'}
                    <input
                      type="checkbox"
                      checked={!pruned.has(l.id)}
                      onchange={() => togglePrune(l.id)}
                    />
                  {/if}
                  <span
                    class="truncate {l.status === 'pruned'
                      ? 'text-muted line-through'
                      : 'text-fg'}"
                  >
                    {l.proposed_title}
                  </span>
                  {#if l.added_by === 'revision'}<Badge tone="accent">revision</Badge>{/if}
                  {#if l.why}<span class="truncate text-muted">— {l.why}</span>{/if}
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
  {/if}
</Page>
