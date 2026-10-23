<script lang="ts">
  import { page } from '$app/stores';
  import { onMount, tick } from 'svelte';
  import { api } from '$lib/api';
  import { topics } from '$lib/topics.svelte';
  import { toasts } from '$lib/toast.svelte';
  import type { Conversation, EventOut, MessageOut, Notebook, Topic } from '$lib/types';
  import { Badge, Button, NotesEditor, Select } from '$lib/ui';
  import MemoryDisclosure from '$lib/ui/MemoryDisclosure.svelte';
  import EventFeed from '$lib/shell/EventFeed.svelte';
  import { cn, scrollBehavior } from '$lib/utils';
  import { settledSave } from '$lib/notebook';
  import Composer from './Composer.svelte';
  import { attemptSavedMessage, messageNote, storedAttempt } from './attempt';

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
  let isMac = $state(false);
  let scroller: HTMLDivElement | null = null;
  // My notes for the current concept, in a panel beside the conversation (over it on
  // narrower screens). Loaded when the panel opens and on each concept switch.
  let notesOpen = $state(false);
  let notebook = $state<Notebook | null>(null);
  let notebookError = $state('');
  let notesSeq = 0;

  onMount(async () => {
    isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
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
      // A later concept switch, or a send (whose reply carries the real levels), supersedes this.
      if (seq !== previewSeq || conversation) return;
      levels = { assistance: p.assistance_level, challenge: p.challenge_level, attempt: p.attempt_logged };
    } catch {
      // The header keeps its placeholders; sending still works.
    }
  }

  async function onConceptChange() {
    if (notesOpen) loadNotes();
    await start();
  }

  async function loadNotes() {
    if (conceptId == null) return;
    const seq = ++notesSeq;
    const forConcept = conceptId;
    notebookError = '';
    try {
      // A save of this concept's notes still on its way (a quick switch back) lands first.
      await settledSave(forConcept);
      const nb = await api.getNotebook(forConcept);
      if (seq === notesSeq) notebook = nb;
    } catch (e) {
      if (seq === notesSeq) notebookError = e instanceof Error ? e.message : String(e);
    }
  }

  function toggleNotes() {
    notesOpen = !notesOpen;
    if (notesOpen) loadNotes();
  }

  // The panel's notebook belongs to the concept it was loaded for.
  const panelNotebook = $derived(notebook && notebook.concept_id === conceptId ? notebook : null);

  /** This session's conversation: created on the first Send, reused by later sends and retries. */
  async function ensureConversation(forConcept: number): Promise<Conversation> {
    if (conversation && conversation.concept_id === forConcept) return conversation;
    conversation = await api.startConversation(topicId, forConcept);
    return conversation;
  }

  /** Send the draft; `attempt` is the Submit attempt button (checked before the tutor replies). */
  async function send(attempt = false) {
    previewSeq++; // a preview still in flight must not overwrite the reply's levels
    if (conceptId == null || !input.trim() || busy) return;
    const forConcept = conceptId;
    const content = input;
    input = '';
    messages = [...messages, { role: 'user', content, is_attempt: attempt }];
    busy = true;
    await tick();
    scroller?.scrollTo({ top: scroller.scrollHeight, behavior: scrollBehavior() });
    let convoId: number | null = null;
    try {
      const convo = await ensureConversation(forConcept);
      convoId = convo.id;
      const r = await api.sendMessage(convo.id, content, attempt);
      const sent = { ...messages[messages.length - 1], attempt_outcome: r.attempt_outcome ?? null };
      messages = [...messages.slice(0, -1), sent, { role: 'tutor', content: r.reply, memory: r.memory ?? [] }];
      events = r.events;
      levels = { assistance: r.assistance_level, challenge: r.challenge_level, attempt: r.attempt_logged };
      await tick();
      scroller?.scrollTo({ top: scroller.scrollHeight, behavior: scrollBehavior() });
    } catch (e) {
      const error = e instanceof Error ? e.message : String(e);
      // An attempt is stored before the tutor runs, so the reply can fail after it was saved.
      const id = convoId;
      // The page's transcript before this send: everything but the optimistic bubble.
      const priorCount = messages.length - 1;
      const stored =
        attempt && id != null ? await storedAttempt(() => api.getConversation(id), content, priorCount) : null;
      if (stored) {
        const c = stored.conversation;
        messages = [...messages.slice(0, -1), stored.message];
        levels = { assistance: c.assistance_level, challenge: c.challenge_level, attempt: c.attempt_logged };
        toasts.show(attemptSavedMessage(error, stored.message.attempt_outcome ?? null), 'error', 12000);
      } else {
        // Nothing was sent (e.g. no API key): take the bubble back, keep the draft, say why.
        messages = messages.slice(0, -1);
        input = content;
        toasts.show(error, 'error', 9000);
      }
    } finally {
      busy = false;
    }
  }

  const conceptName = $derived(topic?.concepts.find((c) => c.id === conceptId)?.name ?? '');
</script>

<svelte:head><title>Tutor · Adaptive Academy</title></svelte:head>

<div class="flex h-[calc(100dvh-3.5rem)] flex-col md:h-screen">
  <!-- Header -->
  <header class="flex flex-wrap items-center gap-3 border-b border-border px-6 py-4 md:px-10">
    <div class="min-w-0 flex-1">
      <h1 class="eyebrow mb-1">Tutor console</h1>
      <div class="flex items-center gap-2">
        {#if topic?.concepts.length}
          <!-- Locked while a send is in flight, so a reply can't land on another concept's session. -->
          <Select bind:value={conceptId} onchange={onConceptChange} disabled={busy} class="w-auto min-w-56" aria-label="Concept">
            {#each topic.concepts as c (c.id)}
              <option value={c.id}>{c.name}</option>
            {/each}
          </Select>
        {:else}
          <span class="text-sm text-muted">No concepts in this topic.</span>
        {/if}
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <Button
        variant={notesOpen ? 'primary' : 'outline'}
        size="sm"
        aria-expanded={notesOpen}
        aria-controls="tutor-notes"
        disabled={conceptId == null}
        onclick={toggleNotes}>{notesOpen ? 'Hide notes' : 'Notes'}</Button
      >
      <Badge tone="info" dot>assistance · {levels.assistance}</Badge>
      <Badge tone="accent" dot>challenge · {levels.challenge}</Badge>
      <Badge tone={levels.attempt ? 'success' : 'neutral'} dot>{levels.attempt ? 'attempt logged' : 'no attempt yet'}</Badge>
    </div>
  </header>

  <div class="flex min-h-0 flex-1">
  <!-- The conversation; on narrower screens the notes panel takes its place while open. -->
  <div class={cn('flex min-w-0 flex-1 flex-col', notesOpen && 'max-lg:hidden')}>
  <!-- Messages -->
  <!-- Focusable so the transcript scrolls from the keyboard; a log, so a new reply is read out. -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div
    bind:this={scroller}
    role="log"
    aria-label="Conversation with the tutor"
    aria-busy={busy}
    tabindex="0"
    class="flex-1 overflow-y-auto px-6 py-6 md:px-10"
  >
    <div class="mx-auto flex max-w-3xl flex-col gap-4">
      {#if !messages.length}
        <div class="mt-12 text-center">
          <h2 class="text-2xl text-fg">{conceptName || 'Pick a concept to begin'}</h2>
          <p class="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted">
            The tutor adapts to your knowledge estimate and won't hand you answers. Write your attempt and press Submit
            attempt, and it can show you the worked solution.
          </p>
        </div>
      {/if}
      {#each messages as m, i (i)}
        {@const note = messageNote(m)}
        <div class="flex {m.role === 'user' ? 'justify-end' : 'justify-start'}">
          <div class="flex max-w-[80%] flex-col {m.role === 'user' ? 'items-end' : ''}">
            <div
              class="whitespace-pre-wrap rounded-[var(--radius-lg)] px-4 py-3 text-sm leading-relaxed {m.role ===
              'user'
                ? 'rounded-br-sm bg-surface-3 text-fg'
                : 'rounded-bl-sm border border-border bg-surface text-fg-dim'}"
            >
              {#if m.role === 'tutor'}<div class="eyebrow mb-1.5 !text-[0.55rem] text-accent">tutor</div>{:else if m.is_attempt}<div class="eyebrow mb-1.5 !text-[0.55rem] text-muted" aria-hidden="true">your attempt</div><span class="sr-only">Your attempt: </span>{:else}<span class="sr-only">You: </span>{/if}{m.content}
            </div>
            {#if note}
              <p class="mt-1.5 text-right text-xs leading-relaxed text-muted" data-testid="attempt-note">{note}</p>
            {/if}
            {#if m.role === 'tutor'}
              <MemoryDisclosure hits={m.memory ?? []} />
            {/if}
          </div>
        </div>
      {/each}
      {#if busy}
        <div class="flex justify-start">
          <div class="flex items-center gap-1.5 rounded-[var(--radius-lg)] rounded-bl-sm border border-border bg-surface px-4 py-3">
            <span class="sr-only">The tutor is thinking…</span>
            {#each [0, 1, 2] as d}
              <span class="size-1.5 animate-bounce rounded-full bg-accent motion-reduce:animate-none" style:animation-delay="{d * 0.15}s" aria-hidden="true"></span>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  </div>

  <!-- Composer -->
  <div class="border-t border-border bg-[color-mix(in_oklab,var(--surface)_40%,transparent)] px-6 py-4 backdrop-blur md:px-10">
    <Composer bind:value={input} disabled={busy || conceptId == null} {isMac} onsend={() => send()} onattempt={() => send(true)} />
    {#if events.length}
      <div class="mx-auto mt-2 max-w-3xl">
        <button type="button" class="eyebrow transition-colors hover:text-fg-dim" aria-expanded={showEvents} onclick={() => (showEvents = !showEvents)}>
          <span aria-hidden="true">{showEvents ? '▾' : '▸'}</span> what the agent did ({events.length})
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

  {#if notesOpen && conceptId != null}
    <aside
      id="tutor-notes"
      aria-labelledby="tutor-notes-title"
      class="flex w-full min-w-0 flex-col gap-4 overflow-y-auto border-border px-6 py-5 lg:w-96 lg:shrink-0 lg:border-l lg:px-5"
    >
      <h2 id="tutor-notes-title" class="eyebrow">Notes · {conceptName}</h2>
      {#if panelNotebook}
        {#key panelNotebook.concept_id}
          <NotesEditor
            conceptId={panelNotebook.concept_id}
            conceptName={panelNotebook.concept_name}
            saved={panelNotebook.note?.body ?? ''}
            savedAt={panelNotebook.note?.updated_at ?? null}
            rows={10}
            onsaved={(n) => {
              if (notebook?.concept_id === n.concept_id) notebook.note = { body: n.body, updated_at: n.updated_at };
            }}
          />
        {/key}
        <p class="text-xs text-muted" data-testid="tutor-notes-counts">
          <span class="nums">{panelNotebook.counts.attempts}</span> attempt{panelNotebook.counts.attempts === 1 ? '' : 's'} ·
          <span class="nums">{panelNotebook.counts.explanations}</span> graded explanation{panelNotebook.counts.explanations === 1 ? '' : 's'} ·
          <span class="nums">{panelNotebook.counts.solutions}</span> worked solution{panelNotebook.counts.solutions === 1 ? '' : 's'}
        </p>
        <a class="text-sm text-accent underline underline-offset-2" href="/topics/{topicId}/notebook?concept={panelNotebook.concept_id}">
          Open the notebook for {panelNotebook.concept_name}
        </a>
      {:else if notebookError}
        <p class="text-sm text-danger" role="alert">Couldn't load your notes. {notebookError}</p>
      {:else}
        <p class="text-sm text-muted">Loading your notes…</p>
      {/if}
    </aside>
  {/if}
  </div>
</div>
