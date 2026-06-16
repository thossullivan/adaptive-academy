<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';

  let title = $state('');
  let goal = $state('');
  let prior_knowledge = $state('');
  let time_budget = $state('');
  let busy = $state(false);
  let status = $state('');

  async function start() {
    if (!title.trim() || !goal.trim() || busy) return;
    busy = true;
    status = 'Creating topic…';
    try {
      const topic = await api.createTopic({ title, goal, prior_knowledge, time_budget });
      status = 'Researching foundational sources… (this can take a moment)';
      await api.runResearch(topic.id);
      await goto(`/topics/${topic.id}/review`);
    } catch (e) {
      status = 'Something went wrong: ' + (e as Error).message;
      busy = false;
    }
  }
</script>

<main class="mx-auto max-w-2xl p-6 flex flex-col gap-4">
  <h1 class="text-xl font-semibold">New topic</h1>
  <p class="text-sm text-gray-500">A quick brainstorm. The Researcher will gather foundational sources you can review.</p>

  <label class="flex flex-col gap-1">
    <span class="text-sm font-medium">What do you want to learn?</span>
    <input class="border rounded px-3 py-2" bind:value={title} placeholder="e.g. Build LLMs from scratch" disabled={busy} />
  </label>
  <label class="flex flex-col gap-1">
    <span class="text-sm font-medium">Your goal</span>
    <textarea class="border rounded px-3 py-2" bind:value={goal} placeholder="What does 'done' look like?" disabled={busy}></textarea>
  </label>
  <label class="flex flex-col gap-1">
    <span class="text-sm font-medium">Prior knowledge</span>
    <textarea class="border rounded px-3 py-2" bind:value={prior_knowledge} placeholder="What do you already know?" disabled={busy}></textarea>
  </label>
  <label class="flex flex-col gap-1">
    <span class="text-sm font-medium">Time budget</span>
    <input class="border rounded px-3 py-2" bind:value={time_budget} placeholder="e.g. ~10 hrs/week" disabled={busy} />
  </label>

  <button class="bg-black text-white rounded px-4 py-2 disabled:opacity-50" onclick={start} disabled={busy || !title.trim() || !goal.trim()}>
    {busy ? 'Working…' : 'Research this topic'}
  </button>
  {#if status}<p class="text-sm text-gray-600">{status}</p>{/if}
</main>
