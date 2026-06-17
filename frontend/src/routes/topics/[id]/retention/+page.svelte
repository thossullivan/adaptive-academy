<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Retention } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge } from '$lib/ui';

  const topicId = Number($page.params.id);
  let data = $state<Retention | null>(null);
  let due = $state<Retention | null>(null);
  let loading = $state(true);

  const gradeTone: Record<string, string> = {
    again: 'var(--danger)',
    hard: 'var(--warn)',
    good: 'var(--success)',
    easy: 'var(--info)'
  };

  async function load() {
    data = await api.listRetention(topicId);
    due = await api.listRetention(topicId, { due: true });
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
  }
</script>

<Page eyebrow="Retention" title="Spaced recall" lead="Retrieval practice woven into the build — revisit before you forget, not after." width="normal">
  {#if loading}
    <div class="grid place-items-center py-24"><span class="eyebrow animate-pulse">loading cards…</span></div>
  {:else}
    <div class="flex flex-col gap-4">
      {#if due && due.cards.length}
        <Card accent pad class="rise">
          <div class="mb-3 flex items-center gap-2">
            <span class="text-accent">◴</span>
            <span class="eyebrow !text-accent">Due now · {due.cards.length}</span>
          </div>
          <div class="flex flex-col gap-3">
            {#each due.cards as c (c.id)}
              <div class="rounded-[var(--radius-md)] border border-border bg-surface-2 p-3.5">
                <p class="text-sm font-medium text-fg">{c.front}</p>
                <p class="mt-1 text-sm text-muted">{c.back}</p>
                <div class="mt-3 flex gap-1.5">
                  {#each ['again', 'hard', 'good', 'easy'] as r}
                    <button
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
                <div class="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3">
                  <p class="text-sm font-medium text-fg">{c.front}</p>
                  <p class="text-sm text-muted">{c.back}</p>
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
                        <button onclick={() => grade(c.id, r)} class="rounded-[var(--radius-sm)] border border-border px-2.5 py-1 text-xs capitalize transition-colors hover:bg-surface-3" style:color={gradeTone[r]}>{r}</button>
                      {/each}
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {:else}
            <p class="py-6 text-center text-sm text-faint">No cards yet — propose some from an assessment.</p>
          {/if}
        </Card>

        {#if data.prompts.length}
          <Card pad class="rise" eyebrow="Recall" title="Open-ended prompts">
            <ul class="flex flex-col gap-1.5">
              {#each data.prompts as p (p.id)}
                <li class="flex items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-2 px-3 py-2 text-sm text-fg-dim">
                  <span class="text-accent-dim">?</span>{p.prompt}
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
