<script lang="ts">
  import { announce } from '$lib/text';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { toasts } from '$lib/toast.svelte';
  import { api } from '$lib/api';
  import type { Retention, DecayItem, DecayGrade } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Markdown, Textarea, LiveStatus } from '$lib/ui';

  const topicId = Number($page.params.id);
  let data = $state<Retention | null>(null);
  let due = $state<Retention | null>(null);
  let loading = $state(true);

  // Decay checks — delayed, unassisted retrieval (§8.6).
  let decay = $state<DecayItem[]>([]);
  let responses = $state<Record<number, string>>({});
  let decayResults = $state<Record<number, DecayGrade>>({});
  let gradingDecay = $state<number | null>(null);
  let status = $state('');

  async function gradeDecayItem(promptId: number) {
    const resp = responses[promptId];
    if (!resp?.trim()) return;
    gradingDecay = promptId;
    try {
      const r = await api.gradeDecay(promptId, resp);
      decayResults[promptId] = r;
      status = announce(status, `Recall ${r.held ? 'held' : 'decayed'}: ${Math.round(r.recall_score * 100)}%. ${r.verdict}`);
    } catch (e) {
      toasts.show(e instanceof Error ? e.message : String(e), 'error', 9000);
    } finally {
      gradingDecay = null;
    }
  }

  const gradeTone: Record<string, string> = {
    again: 'var(--danger)',
    hard: 'var(--warn)',
    good: 'var(--success)',
    easy: 'var(--info)'
  };

  async function load() {
    data = await api.listRetention(topicId);
    due = await api.listRetention(topicId, { due: true });
    decay = (await api.listDecay(topicId).catch(() => ({ items: [] }))).items;
    // bind:value needs a defined string for every textarea (its fallback can't take undefined).
    for (const d of decay) responses[d.prompt_id] ??= '';
    loading = false;
  }
  onMount(load);

  async function review(id: number, status: string) {
    await api.reviewCard(id, status);
    await load();
  }
  async function grade(id: number, result: string) {
    await api.gradeCard(id, result);
    await load();
    status = announce(status, `Card graded ${result}.`);
  }
</script>

<svelte:head><title>Retention · Adaptive Academy</title></svelte:head>

<Page eyebrow="Retention" title="Review before you forget" lead="Flashcards and recall checks, spaced out so you go back to each idea just before you'd forget it." width="normal">
  <LiveStatus message={status} />
  {#if loading}
    <div class="grid place-items-center py-24" role="status"><span class="eyebrow animate-pulse">loading cards…</span></div>
  {:else}
    <div class="flex flex-col gap-4">
      {#if decay.length}
        <Card accent pad class="rise">
          <div class="mb-1 flex items-center gap-2">
            <span class="text-accent" aria-hidden="true">↺</span>
            <h2 class="eyebrow !text-accent">Decay checks · {decay.length}</h2>
          </div>
          <p class="mb-3 text-sm text-muted">Some time has passed since you learned these. Answer from memory, with no notes and no tutor, to see what has stuck.</p>
          <div class="flex flex-col gap-3">
            {#each decay as d (d.prompt_id)}
              <div class="rounded-[var(--radius-md)] border border-border bg-surface-2 p-3.5" role="group" aria-labelledby="decay-prompt-{d.prompt_id}">
                <div class="flex items-center gap-2">
                  <Badge tone="neutral" mono>{d.concept_name}</Badge>
                  {#if d.last_result}<span class="eyebrow !text-[0.55rem]">last: {d.last_result}</span>{/if}
                </div>
                <p class="mt-2 text-sm text-fg-dim" id="decay-prompt-{d.prompt_id}"><Markdown text={d.prompt} /></p>
                {#if decayResults[d.prompt_id]}
                  {@const r = decayResults[d.prompt_id]}
                  <div class="mt-3 rounded-[var(--radius-sm)] border border-border p-3 text-sm">
                    <div class="flex items-center gap-2">
                      <Badge tone={r.held ? 'success' : 'danger'} dot>{r.held ? 'held' : 'decayed'}</Badge>
                      <span class="nums text-muted">recall {Math.round(r.recall_score * 100)}%{#if r.baseline_score != null} · was {Math.round(r.baseline_score * 100)}%{/if}{#if r.decay_delta != null} · Δ {r.decay_delta > 0 ? '+' : ''}{r.decay_delta.toFixed(2)}{/if}</span>
                    </div>
                    <p class="mt-2 text-fg-dim"><Markdown text={r.verdict} block /></p>
                  </div>
                {:else}
                  <Textarea class="mt-2" bind:value={responses[d.prompt_id]} rows={4} aria-label="Your answer, from memory" placeholder="From memory, no looking…" />
                  <Button size="sm" class="mt-2" onclick={() => gradeDecayItem(d.prompt_id)} disabled={gradingDecay === d.prompt_id || !responses[d.prompt_id]?.trim()}>
                    {gradingDecay === d.prompt_id ? 'Checking…' : 'Check recall'}
                  </Button>
                {/if}
              </div>
            {/each}
          </div>
        </Card>
      {/if}

      {#if due && due.cards.length}
        <Card accent pad class="rise">
          <div class="mb-3 flex items-center gap-2">
            <span class="text-accent" aria-hidden="true">◴</span>
            <h2 class="eyebrow !text-accent">Due now · {due.cards.length}</h2>
          </div>
          <div class="flex flex-col gap-3">
            {#each due.cards as c (c.id)}
              <div class="rounded-[var(--radius-md)] border border-border bg-surface-2 p-3.5" role="group" aria-labelledby="due-front-{c.id}">
                <p class="text-sm font-medium text-fg" id="due-front-{c.id}"><Markdown text={c.front} /></p>
                <p class="mt-1 text-sm text-muted"><Markdown text={c.back} /></p>
                <div class="mt-3 flex gap-1.5">
                  {#each ['again', 'hard', 'good', 'easy'] as r}
                    <button
                      type="button"
                      onclick={() => grade(c.id, r)}
                      class="flex-1 rounded-[var(--radius-sm)] border border-border py-1.5 text-xs font-medium capitalize transition-colors hover:bg-surface-3"
                      style:color={gradeTone[r]}
                    >{r}</button>
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        </Card>
      {/if}

      {#if data}
        <Card pad class="rise" eyebrow="Deck" title="All cards">
          {#snippet header()}<Badge mono tone="neutral">{data?.cards.length ?? 0}</Badge>{/snippet}
          {#if data.cards.length}
            <div class="grid gap-2.5 md:grid-cols-2">
              {#each data.cards as c (c.id)}
                <div class="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3" role="group" aria-labelledby="deck-front-{c.id}">
                  <p class="text-sm font-medium text-fg" id="deck-front-{c.id}"><Markdown text={c.front} /></p>
                  <p class="text-sm text-muted"><Markdown text={c.back} /></p>
                  <div class="flex items-center gap-1.5">
                    <Badge mono tone={c.status === 'active' ? 'success' : c.status === 'proposed' ? 'accent' : 'neutral'}>{c.status}</Badge>
                    <span class="eyebrow !text-[0.55rem]">{c.reps} reps · {c.interval}d</span>
                  </div>
                  <div class="flex flex-wrap gap-1.5">
                    {#if c.status === 'proposed'}
                      <Button variant="outline" size="sm" onclick={() => review(c.id, 'active')}>Activate</Button>
                      <Button variant="ghost" size="sm" onclick={() => review(c.id, 'suspended')}>Suspend</Button>
                    {:else if c.status === 'active'}
                      {#each ['again', 'hard', 'good', 'easy'] as r}
                        <button type="button" onclick={() => grade(c.id, r)} class="rounded-[var(--radius-sm)] border border-border px-2.5 py-1 text-xs capitalize transition-colors hover:bg-surface-3" style:color={gradeTone[r]}>{r}</button>
                      {/each}
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {:else}
            <p class="py-6 text-center text-sm text-faint">No cards yet. They are suggested after you're assessed on a concept.</p>
          {/if}
        </Card>

        {#if data.prompts.length}
          <Card pad class="rise" eyebrow="Recall" title="Open-ended prompts">
            <ul class="flex flex-col gap-1.5">
              {#each data.prompts as p (p.id)}
                <li class="flex items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-2 px-3 py-2 text-sm text-fg-dim">
                  <span class="text-accent" aria-hidden="true">?</span><Markdown text={p.prompt} class="min-w-0" />
                  <Badge mono tone="neutral" class="ml-auto">{p.status}</Badge>
                </li>
              {/each}
            </ul>
          </Card>
        {/if}
      {/if}
    </div>
  {/if}
</Page>
