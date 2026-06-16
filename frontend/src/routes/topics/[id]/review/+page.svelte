<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { SourceDoc, Foundation, EventOut } from '$lib/types';

  const topicId = Number($page.params.id);
  let foundation = $state<Foundation | null>(null);
  let sources = $state<SourceDoc[]>([]);
  let events = $state<EventOut[]>([]);
  let keep = $state<Record<number, boolean>>({});
  let busy = $state(false);
  let saved = $state(false);

  onMount(async () => {
    try {
      foundation = await api.getFoundation(topicId);
    } catch { foundation = null; }
    sources = await api.listSources(topicId, 'proposed');
    for (const s of sources) keep[s.id] = true;
    events = await api.listEvents(topicId);
  });

  async function save() {
    busy = true;
    const accepted = sources.filter((s) => keep[s.id]).map((s) => s.id);
    const pruned = sources.filter((s) => !keep[s.id]).map((s) => s.id);
    try {
      await api.reviewSources(topicId, accepted, pruned);
      saved = true;
    } finally {
      busy = false;
    }
  }
</script>

<main class="mx-auto max-w-3xl p-6 flex flex-col gap-4">
  <h1 class="text-xl font-semibold">Review reading list</h1>

  {#if foundation}
    <section class="border rounded p-4 bg-gray-50">
      <p class="text-sm">{foundation.overview}</p>
      {#if foundation.key_concepts.length}
        <div class="mt-2 flex flex-wrap gap-1">
          {#each foundation.key_concepts as c}
            <span class="text-xs bg-gray-200 rounded px-2 py-0.5">{c}</span>
          {/each}
        </div>
      {/if}
    </section>
  {/if}

  {#if saved}
    <p class="text-green-700 text-sm">Reading list saved.</p>
  {/if}

  <ul class="flex flex-col gap-2">
    {#each sources as s (s.id)}
      <li class="border rounded p-3 flex gap-3 items-start">
        <input type="checkbox" class="mt-1" bind:checked={keep[s.id]} />
        <div class="flex flex-col gap-1">
          <a href={s.url} target="_blank" rel="noreferrer" class="font-medium underline">{s.title}</a>
          <div class="text-xs text-gray-500">tier {s.tier} · {s.angle}</div>
          {#if s.summary}<p class="text-sm">{s.summary}</p>{/if}
          {#if s.why}<p class="text-sm text-gray-600">Why: {s.why}</p>{/if}
        </div>
      </li>
    {/each}
  </ul>

  <button class="bg-black text-white rounded px-4 py-2 disabled:opacity-50 self-start" onclick={save} disabled={busy || !sources.length}>
    {busy ? 'Saving…' : 'Save reading list'}
  </button>

  {#if events.length}
    <details class="text-sm text-gray-600">
      <summary class="cursor-pointer">What the agents did ({events.length})</summary>
      <ul class="mt-2 flex flex-col gap-1">
        {#each events as e}<li><span class="font-mono text-xs">{e.kind}</span> — {e.detail}</li>{/each}
      </ul>
    </details>
  {/if}
</main>
