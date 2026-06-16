<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Conversation, EventOut, MessageOut, Topic } from '$lib/types';

  let topic = $state<Topic | null>(null);
  let conversation = $state<Conversation | null>(null);
  let messages = $state<MessageOut[]>([]);
  let events = $state<EventOut[]>([]);
  let levels = $state({ assistance: '—', challenge: '—', attempt: false });
  let input = $state('');
  let busy = $state(false);

  onMount(async () => {
    const topics = await api.listTopics();
    topic = topics[0] ?? null;
    if (topic && topic.concepts[0]) {
      conversation = await api.startConversation(topic.id, topic.concepts[0].id);
      levels = {
        assistance: conversation.assistance_level,
        challenge: conversation.challenge_level,
        attempt: conversation.attempt_logged
      };
    }
  });

  async function send() {
    if (!conversation || !input.trim() || busy) return;
    const content = input;
    input = '';
    messages = [...messages, { role: 'user', content }];
    busy = true;
    try {
      const r = await api.sendMessage(conversation.id, content);
      messages = [...messages, { role: 'tutor', content: r.reply }];
      events = r.events;
      levels = { assistance: r.assistance_level, challenge: r.challenge_level, attempt: r.attempt_logged };
    } finally {
      busy = false;
    }
  }
</script>

<main class="mx-auto max-w-2xl p-6">
  <header class="mb-4">
    <h1 class="text-2xl font-semibold">{topic?.title ?? 'Adaptive Academy'}</h1>
    <p class="text-sm text-gray-500">
      Concept: {topic?.concepts[0]?.name ?? '—'}
    </p>
    <div class="mt-2 flex gap-2 text-xs">
      <span class="rounded bg-blue-100 px-2 py-1">assistance: {levels.assistance}</span>
      <span class="rounded bg-purple-100 px-2 py-1">challenge: {levels.challenge}</span>
      <span class="rounded px-2 py-1 {levels.attempt ? 'bg-green-100' : 'bg-gray-100'}">
        attempt: {levels.attempt ? 'logged' : 'not yet'}
      </span>
    </div>
  </header>

  <section class="mb-4 flex flex-col gap-3">
    {#each messages as m}
      <div class="rounded-lg px-3 py-2 {m.role === 'user' ? 'self-end bg-gray-100' : 'self-start bg-blue-50'}">
        {m.content}
      </div>
    {/each}
    {#if busy}<div class="self-start text-sm text-gray-400">tutor is thinking…</div>{/if}
  </section>

  <form class="flex gap-2" onsubmit={(e) => { e.preventDefault(); send(); }}>
    <input
      class="flex-1 rounded border px-3 py-2"
      bind:value={input}
      placeholder="Ask the tutor… (it won't just hand you the answer)"
    />
    <button class="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50" disabled={busy}>
      Send
    </button>
  </form>

  {#if events.length}
    <details class="mt-6 text-xs text-gray-500">
      <summary>What the agents did ({events.length})</summary>
      <ul class="mt-2 space-y-1">
        {#each events as e}
          <li><code>{e.kind}</code> {e.detail}</li>
        {/each}
      </ul>
    </details>
  {/if}
</main>
