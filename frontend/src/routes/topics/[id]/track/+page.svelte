<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Curriculum } from '$lib/types';

  const topicId = Number($page.params.id);
  let cur = $state<Curriculum | null>(null);
  const cycle: Record<string, string> = { todo: 'doing', doing: 'done', done: 'todo' };

  onMount(async () => {
    try { cur = await api.getCurriculum(topicId); } catch { cur = null; }
  });

  async function toggle(itemId: number, status: string) {
    const next = cycle[status] ?? 'todo';
    const updated = await api.updateItem(itemId, { status: next });
    if (!cur) return;
    for (const p of cur.phases)
      for (const it of p.items) if (it.id === itemId) it.status = updated.status;
  }

  async function exportMd() {
    const md = await api.exportCurriculumMd(topicId);
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `track-${topicId}.md`; a.click();
    URL.revokeObjectURL(url);
  }
</script>

<main class="mx-auto max-w-3xl p-6 flex flex-col gap-4">
  {#if cur}
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-semibold">{cur.track.title}</h1>
      <div class="flex items-center gap-3">
        <a class="text-sm underline" href="/topics/{topicId}/assess">Assess →</a>
        <a class="text-sm underline" href="/topics/{topicId}/retention">Retention →</a>
        <button class="text-sm underline" onclick={exportMd}>Export markdown</button>
      </div>
    </div>
    {#if cur.track.overview}<p class="text-sm text-gray-600">{cur.track.overview}</p>{/if}

    {#each cur.phases as p (p.id)}
      <section class="border rounded p-4 flex flex-col gap-2">
        <h2 class="font-medium">
          Phase {p.position + 1} — {p.title}
          {#if p.est_hours}<span class="text-xs text-gray-500">({p.est_hours})</span>{/if}
          {#each p.flags as f}<span class="text-xs bg-gray-200 rounded px-1">{f}</span>{/each}
        </h2>
        <ul class="flex flex-col gap-1">
          {#each p.items as it (it.id)}
            <li class="flex gap-2 items-center text-sm {it.is_remediation ? 'bg-amber-50 rounded px-1' : ''}">
              <button class="font-mono text-xs border rounded px-1"
                      onclick={() => toggle(it.id, it.status)}>{it.status}</button>
              <span class="text-xs text-gray-500">({it.type})</span>
              <span>{it.text}</span>
              {#if it.is_remediation}<span class="text-xs bg-amber-200 rounded px-1">remediation</span>{/if}
            </li>
          {/each}
        </ul>
        {#if p.deliverable}
          <div class="text-sm bg-yellow-50 border rounded p-2">
            🎯 Ship ({p.deliverable.kind}): {p.deliverable.text}
            {#if p.deliverable.acceptance_criteria.length}
              <ul class="list-disc ml-5 text-xs text-gray-600">
                {#each p.deliverable.acceptance_criteria as c}<li>{c}</li>{/each}
              </ul>
            {/if}
          </div>
        {/if}
      </section>
    {/each}

    {#each cur.sidebars as s (s.id)}
      <aside class="border-l-4 border-gray-300 pl-3 text-sm">
        <div class="font-medium">{s.title} <span class="text-xs text-gray-500">{s.kind}</span></div>
        <p class="text-gray-600 whitespace-pre-line">{s.body}</p>
      </aside>
    {/each}

    {#if cur.events.length}
      <details class="text-sm text-gray-600">
        <summary class="cursor-pointer">What the agents did ({cur.events.length})</summary>
        <ul class="mt-2 flex flex-col gap-1">
          {#each cur.events as e}<li><span class="font-mono text-xs">{e.kind}</span> — {e.detail}</li>{/each}
        </ul>
      </details>
    {/if}
  {:else}
    <p class="text-sm text-gray-500">No curriculum yet.</p>
  {/if}
</main>
