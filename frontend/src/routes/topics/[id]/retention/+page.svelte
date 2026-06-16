<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Retention } from '$lib/types';

  const topicId = Number($page.params.id);
  let data = $state<Retention | null>(null);
  let due = $state<Retention | null>(null);

  async function load() {
    data = await api.listRetention(topicId);
    due = await api.listRetention(topicId, { due: true });
  }
  onMount(load);

  async function review(id: number, status: string) { await api.reviewCard(id, status); await load(); }
  async function grade(id: number, result: string) { await api.gradeCard(id, result); await load(); }
</script>

<main class="mx-auto max-w-3xl p-6 flex flex-col gap-4">
  <h1 class="text-xl font-semibold">Retention</h1>
  {#if due && due.cards.length}
    <section class="border rounded p-3 bg-amber-50 flex flex-col gap-2">
      <h2 class="font-medium text-sm">Due now ({due.cards.length})</h2>
      {#each due.cards as c (c.id)}
        <div class="flex flex-col gap-1 text-sm">
          <div><b>{c.front}</b> — {c.back}</div>
          <div class="flex gap-2">
            {#each ['again', 'hard', 'good', 'easy'] as r}
              <button class="border rounded px-2" onclick={() => grade(c.id, r)}>{r}</button>
            {/each}
          </div>
        </div>
      {/each}
    </section>
  {/if}
  {#if data}
    <h2 class="font-medium text-sm">Cards</h2>
    <ul class="flex flex-col gap-2">
      {#each data.cards as c (c.id)}
        <li class="border rounded p-3 flex flex-col gap-1 text-sm">
          <div><b>{c.front}</b> — {c.back}</div>
          <div class="text-xs text-gray-500">status {c.status} · reps {c.reps} · interval {c.interval}d</div>
          <div class="flex gap-2">
            {#if c.status === 'proposed'}
              <button class="underline" onclick={() => review(c.id, 'active')}>activate</button>
              <button class="underline" onclick={() => review(c.id, 'suspended')}>suspend</button>
            {:else if c.status === 'active'}
              {#each ['again', 'hard', 'good', 'easy'] as r}
                <button class="border rounded px-2" onclick={() => grade(c.id, r)}>{r}</button>
              {/each}
            {/if}
          </div>
        </li>
      {/each}
    </ul>
    <h2 class="font-medium text-sm">Recall prompts</h2>
    <ul class="flex flex-col gap-1 text-sm">
      {#each data.prompts as p (p.id)}<li class="border rounded p-2">{p.prompt} <span class="text-xs text-gray-500">({p.status})</span></li>{/each}
    </ul>
  {/if}
</main>
