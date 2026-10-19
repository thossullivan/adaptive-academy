<script lang="ts">
  import { page } from '$app/stores';
  import { onMount, tick } from 'svelte';
  import { api } from '$lib/api';
  import { topics } from '$lib/topics.svelte';
  import { toasts } from '$lib/toast.svelte';
  import type { Conversation, EventOut, MessageOut, Topic } from '$lib/types';
  import { Badge, Select, Button } from '$lib/ui';
  import MemoryDisclosure from '$lib/ui/MemoryDisclosure.svelte';
  import EventFeed from '$lib/shell/EventFeed.svelte';

  const topicId = Number($page.params.id);
  let topic = $state<Topic | null>(null);
  let conceptId = $state<number | null>(null);
  let conversation = $state<Conversation | null>(null);
  let messages = $state<MessageOut[]>([]);
  let events = $state<EventOut[]>([]);
  let levels = $state({ assistance: '—', challenge: '—', attempt: false });
  let input = $state('');
  let busy = $state(false);
  let showEvents = $state(false);
  let scroller: HTMLDivElement | null = null;

  onMount(async () => {
    topic = topics.list.find((t) => t.id === topicId) ?? (await api.getTopic(topicId).catch(() => null));
    if (topic && topics.currentId !== topicId) topics.select(topicId);
    if (topic?.concepts.length) {
      // Honor a ?concept=ID deep-link (from Today / Constellation), else first concept.
      const wanted = Number($page.url.searchParams.get('concept'));
      conceptId = topic.concepts.some((c) => c.id === wanted) ? wanted : topic.concepts[0].id;
      await start();
    }
  });

  // Each visit or concept switch is a fresh session, but its conversation row is created only
  // on the first Send, so browsing the Tutor saves nothing. Until then the header shows the
  // levels that session would use (a read-only preview) and, as for any new session, no attempt.
  let previewSeq = 0;
  async function start() {
    if (conceptId == null) return;
    const seq = ++previewSeq;
    conversation = null;
    messages = [];
    events = [];
    levels = { assistance: '—', challenge: '—', attempt: false };
    try {
      const p = await api.previewConversation(topicId, conceptId);
      if (seq !== previewSeq) return; // a later concept switch superseded this one
      levels = { assistance: p.assistance_level, challenge: p.challenge_level, attempt: p.attempt_logged };
    } catch {
      // The header keeps its placeholders; sending still works.
    }
  }

  async function onConceptChange() {
    await start();
  }

  /** This session's conversation: created on the first Send, reused by later sends and retries. */
  async function ensureConversation(forConcept: number): Promise<Conversation> {
    if (conversation && conversation.concept_id === forConcept) return conversation;
    conversation = await api.startConversation(topicId, forConcept);
    return conversation;
  }

  async function send() {
    if (conceptId == null || !input.trim() || busy) return;
    const forConcept = conceptId;
    const content = input;
    input = '';
    messages = [...messages, { role: 'user', content }];
    busy = true;
    await tick();
    scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
    try {
      const convo = await ensureConversation(forConcept);
      const r = await api.sendMessage(convo.id, content);
      messages = [...messages, { role: 'tutor', content: r.reply, memory: r.memory ?? [] }];
      events = r.events;
      levels = { assistance: r.assistance_level, challenge: r.challenge_level, attempt: r.attempt_logged };
      await tick();
      scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
    } catch (e) {
      // Nothing was sent (e.g. no API key): take the bubble back, keep the draft, say why.
      messages = messages.slice(0, -1);
      input = content;
      toasts.show(e instanceof Error ? e.message : String(e), 'error', 9000);
    } finally {
      busy = false;
    }
  }

  const conceptName = $derived(topic?.concepts.find((c) => c.id === conceptId)?.name ?? '');
</script>

<div class="flex h-[calc(100dvh-3.5rem)] flex-col md:h-screen">
  <!-- Header -->
  <header class="flex flex-wrap items-center gap-3 border-b border-border px-6 py-4 md:px-10">
    <div class="min-w-0 flex-1">
      <div class="eyebrow mb-1">Tutor console</div>
      <div class="flex items-center gap-2">
        {#if topic?.concepts.length}
          <!-- Locked while a send is in flight, so a reply can't land on another concept's session. -->
          <Select bind:value={conceptId} onchange={onConceptChange} disabled={busy} class="w-auto min-w-56">
            {#each topic.concepts as c (c.id)}
              <option value={c.id}>{c.name}</option>
            {/each}
          </Select>
        {:else}
          <span class="text-sm text-muted">No concepts in this topic.</span>
        {/if}
      </div>
    </div>
    <div class="flex items-center gap-2">
      <Badge tone="info" dot>assistance · {levels.assistance}</Badge>
      <Badge tone="accent" dot>challenge · {levels.challenge}</Badge>
      <Badge tone={levels.attempt ? 'success' : 'neutral'} dot>{levels.attempt ? 'attempt logged' : 'no attempt yet'}</Badge>
    </div>
  </header>

  <!-- Messages -->
  <div bind:this={scroller} class="flex-1 overflow-y-auto px-6 py-6 md:px-10">
    <div class="mx-auto flex max-w-3xl flex-col gap-4">
      {#if !messages.length}
        <div class="mt-12 text-center">
          <h2 class="text-2xl text-fg">{conceptName || 'Pick a concept to begin'}</h2>
          <p class="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted">
            The tutor adapts to your knowledge estimate and won't hand you answers — log an attempt and it'll open up
            the worked solution.
          </p>
        </div>
      {/if}
      {#each messages as m, i (i)}
        <div class="flex {m.role === 'user' ? 'justify-end' : 'justify-start'}">
          <div class="flex max-w-[80%] flex-col">
            <div
              class="whitespace-pre-wrap rounded-[var(--radius-lg)] px-4 py-3 text-sm leading-relaxed {m.role ===
              'user'
                ? 'rounded-br-sm bg-surface-3 text-fg'
                : 'rounded-bl-sm border border-border bg-surface text-fg-dim'}"
            >
              {#if m.role === 'tutor'}<div class="eyebrow mb-1.5 !text-[0.55rem] text-accent">tutor</div>{/if}{m.content}
            </div>
            {#if m.role === 'tutor'}
              <MemoryDisclosure hits={m.memory ?? []} />
            {/if}
          </div>
        </div>
      {/each}
      {#if busy}
        <div class="flex justify-start">
          <div class="flex items-center gap-1.5 rounded-[var(--radius-lg)] rounded-bl-sm border border-border bg-surface px-4 py-3">
            {#each [0, 1, 2] as d}
              <span class="size-1.5 animate-bounce rounded-full bg-accent" style:animation-delay="{d * 0.15}s"></span>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  </div>

  <!-- Composer -->
  <div class="border-t border-border bg-[color-mix(in_oklab,var(--surface)_40%,transparent)] px-6 py-4 backdrop-blur md:px-10">
    <form
      class="mx-auto flex max-w-3xl items-end gap-2"
      onsubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <textarea
        bind:value={input}
        rows="1"
        placeholder="Ask the tutor… (it won't just hand you the answer)"
        disabled={busy || conceptId == null}
        onkeydown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        class="max-h-40 min-h-[2.75rem] flex-1 resize-none rounded-[var(--radius-md)] border border-border bg-surface-2 px-3.5 py-3 text-sm leading-relaxed text-fg placeholder:text-faint transition-colors hover:border-border-strong focus:border-accent focus:outline-none disabled:opacity-50"
      ></textarea>
      <Button type="submit" size="lg" disabled={busy || conceptId == null || !input.trim()}>Send</Button>
    </form>
    {#if events.length}
      <div class="mx-auto mt-2 max-w-3xl">
        <button class="eyebrow transition-colors hover:text-fg-dim" onclick={() => (showEvents = !showEvents)}>
          {showEvents ? '▾' : '▸'} what the agent did ({events.length})
        </button>
        {#if showEvents}
          <div class="mt-1.5 rounded-[var(--radius-md)] border border-border bg-surface p-2">
            <EventFeed {events} />
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>
