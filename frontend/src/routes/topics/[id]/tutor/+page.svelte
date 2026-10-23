<script lang="ts">
  import { page } from '$app/stores';
  import { onMount, tick } from 'svelte';
  import { api } from '$lib/api';
  import { topics } from '$lib/topics.svelte';
  import { toasts } from '$lib/toast.svelte';
  import type { Conversation, EventOut, MessageOut, Notebook, Topic } from '$lib/types';
  import { Badge, Button, Markdown, NotesEditor, Select } from '$lib/ui';
  import MemoryDisclosure from '$lib/ui/MemoryDisclosure.svelte';
  import EventFeed from '$lib/shell/EventFeed.svelte';
  import { cn, scrollBehavior } from '$lib/utils';
  import { settledSave } from '$lib/notebook';
  import Composer from './Composer.svelte';
  import {
    WORKED_SOLUTION_LABEL,
    attemptChip,
    attemptSavedMessage,
    messageNote,
    starterPrompts,
    storedAttempt
  } from './attempt';

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
  let composer = $state<ReturnType<typeof Composer> | null>(null);
  // The header's session chips scroll sideways on a phone; while they overflow, the row takes
  // focus so it can be scrolled from the keyboard too.
  let chipRow = $state<HTMLDivElement | null>(null);
  let chipsOverflow = $state(false);
  // More chips past the left or right edge: a fade marks that edge.
  let chipsLeft = $state(false);
  let chipsRight = $state(false);
  function measureChips() {
    const row = chipRow;
    if (!row) return;
    chipsOverflow = row.scrollWidth > row.clientWidth + 1;
    chipsLeft = chipsOverflow && row.scrollLeft > 1;
    chipsRight = chipsOverflow && row.scrollLeft + row.clientWidth < row.scrollWidth - 1;
  }
  $effect(() => {
    const row = chipRow;
    if (!row) return;
    void [levels.assistance, levels.challenge, levels.attempt];
    measureChips();
    const ro = new ResizeObserver(measureChips);
    ro.observe(row);
    return () => ro.disconnect();
  });
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
    // Drop the one shown: a quick switch back to it must not remount the editor from that
    // older copy (it predates the save made on the way out). The editor mounts only from a
    // load that waited for the concept's saves.
    notebook = null;
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
      messages = [
        ...messages.slice(0, -1),
        sent,
        { role: 'tutor', content: r.reply, memory: r.memory ?? [], reveals_solution: !!r.reveals_solution }
      ];
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
  const starters = $derived(starterPrompts(conceptName));

  /** A starter prompt fills the composer for the learner to edit or send; it is never sent. */
  async function useStarter(text: string) {
    if (input.trim()) return; // never over a draft (the starters hide once there is one)
    input = text;
    await tick();
    composer?.focus();
  }

  // The gate in three steps, for the empty Tutor.
  const STEPS = [
    { title: 'Ask', text: 'Ask questions. The tutor answers with hints and questions, not the answer.' },
    { title: 'Attempt', text: 'Write your reasoning or a first step, then press Submit attempt.' },
    { title: 'Solution', text: 'Once your attempt is logged, the tutor can show you the worked solution.' }
  ];
</script>

<svelte:head><title>Tutor · Adaptive Academy</title></svelte:head>

<div class="flex h-[calc(100dvh-3.5rem)] flex-col md:h-screen">
  <!-- Header -->
  <!-- Phone: the concept and Notes on one row, the session chips on one sideways-scrolling row. -->
  <header class="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-6 py-3 md:px-10 md:py-4">
    <div class="min-w-0 flex-1">
      <h1 class="eyebrow mb-1 max-md:sr-only">Tutor</h1>
      {#if topic?.concepts.length}
        <!-- Locked while a send is in flight, so a reply can't land on another concept's session. -->
        <Select bind:value={conceptId} onchange={onConceptChange} disabled={busy} class="w-full md:w-fit md:min-w-56 md:max-w-full" aria-label="Concept">
          {#each topic.concepts as c (c.id)}
            <option value={c.id}>{c.name}</option>
          {/each}
        </Select>
      {:else}
        <span class="text-sm text-muted">No concepts in this topic.</span>
      {/if}
    </div>
    <!-- A toggle: pressed while the notes panel is open (an outline, so it never competes with Send). -->
    <Button
      variant="outline"
      size="sm"
      class={cn(
        'max-md:h-10',
        notesOpen && 'border-accent bg-accent-wash text-fg hover:border-accent-bright hover:text-fg'
      )}
      aria-pressed={notesOpen}
      aria-controls={notesOpen ? 'tutor-notes' : undefined}
      disabled={conceptId == null}
      onclick={toggleNotes}
      ><svg viewBox="0 0 16 16" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"
        ><path d="M4 2.5h6l2.5 2.5v8.5h-8.5z M6.5 7.5h4 M6.5 10h4" stroke-linejoin="round" /></svg
      >Notes</Button
    >
    <!-- Scrolls sideways on a phone when the chips don't fit; focusable then, so it scrolls from
         the keyboard, and a fade at a cut edge says there is more. The gate chip comes first. -->
    <div class="relative min-w-0 max-md:-mx-6 max-md:w-[calc(100%+3rem)]">
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <div
        bind:this={chipRow}
        role="group"
        aria-label="This session"
        tabindex={chipsOverflow ? 0 : undefined}
        onscroll={measureChips}
        class="flex items-center gap-2 max-md:overflow-x-auto max-md:px-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        data-testid="tutor-chips"
      >
        <Badge tone={levels.attempt ? 'success' : 'neutral'} dot class="shrink-0 whitespace-nowrap"
          >{levels.attempt ? 'attempt logged' : 'no attempt yet'}</Badge
        >
        <Badge tone="info" dot class="shrink-0 whitespace-nowrap">assistance · {levels.assistance}</Badge>
        <Badge tone="accent" dot class="shrink-0 whitespace-nowrap">challenge · {levels.challenge}</Badge>
      </div>
      <div
        aria-hidden="true"
        class="pointer-events-none absolute inset-y-0 left-0 w-8 bg-gradient-to-r from-bg to-transparent transition-opacity duration-150 md:hidden {chipsLeft ? 'opacity-100' : 'opacity-0'}"
        data-testid="chips-fade-left"
      ></div>
      <div
        aria-hidden="true"
        class="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-bg to-transparent transition-opacity duration-150 md:hidden {chipsRight ? 'opacity-100' : 'opacity-0'}"
        data-testid="chips-fade-right"
      ></div>
    </div>
  </header>

  <div class="flex min-h-0 flex-1">
  <!-- The conversation; on narrower screens the notes panel takes its place while open. -->
  <div class={cn('flex min-w-0 flex-1 flex-col', notesOpen && 'max-lg:hidden')}>
  <!-- Messages -->
  <!-- Focusable so the transcript scrolls from the keyboard; a log, so a new reply is read out. -->
  <!-- `relative` makes it the containing block of the screen-reader-only labels inside it, so
       they are clipped with the transcript instead of stretching the page below it. -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div
    bind:this={scroller}
    role="log"
    aria-label="Conversation with the tutor"
    aria-busy={busy}
    tabindex="0"
    class="relative min-h-0 flex-1 overflow-y-auto px-6 py-6 md:px-10"
  >
    <div class="mx-auto flex max-w-3xl flex-col gap-4">
      {#if !messages.length}
        <div class="mx-auto w-full max-w-2xl md:mt-8" data-testid="tutor-empty">
          <h2 class="text-center text-2xl text-fg [overflow-wrap:anywhere]">{conceptName || 'Pick a concept to begin'}</h2>
          <p class="mx-auto mt-2 max-w-md text-center text-sm leading-relaxed text-muted">
            The tutor adapts to your knowledge estimate and won't hand you the answer until you've tried.
          </p>
          <ol class="mt-5 grid gap-2 md:grid-cols-3" aria-label="How the tutor works">
            {#each STEPS as step, n (step.title)}
              <li class="flex gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3.5 py-2.5 md:flex-col md:gap-2 md:py-3">
                <span
                  class="nums grid size-6 shrink-0 place-items-center rounded-full border border-accent text-xs font-medium text-accent"
                  aria-hidden="true">{n + 1}</span
                >
                <p class="min-w-0 text-xs leading-relaxed text-muted">
                  <span class="text-sm font-medium text-fg md:mb-0.5 md:block">{step.title}<span class="sr-only">:</span></span>
                  {step.text}
                </p>
              </li>
            {/each}
          </ol>
          {#if starters.length && !input.trim()}
            <div class="mt-5" role="group" aria-labelledby="tutor-starters-label">
              <p id="tutor-starters-label" class="text-xs text-muted">Not sure where to start? Pick one to put it in the message box.</p>
              <div class="mt-2 grid gap-2 md:grid-cols-2">
                {#each starters as starter (starter)}
                  <button
                    type="button"
                    class="min-h-11 rounded-[var(--radius-md)] border border-border-strong bg-surface-2 px-3.5 py-2.5 text-left text-sm leading-snug text-fg-dim transition-colors hover:border-faint hover:text-fg disabled:opacity-50"
                    disabled={busy || conceptId == null}
                    onclick={() => useStarter(starter)}>{starter}</button
                  >
                {/each}
              </div>
            </div>
          {/if}
        </div>
      {/if}
      {#each messages as m, i (i)}
        {@const note = messageNote(m)}
        {@const chip = attemptChip(m, busy && i === messages.length - 1)}
        {@const solution = m.role === 'tutor' && !!m.reveals_solution}
        <div class="flex {m.role === 'user' ? 'justify-end' : 'justify-start'}">
          <div class="flex min-w-0 max-w-[88%] flex-col md:max-w-[80%] {m.role === 'user' ? 'items-end' : ''}">
            <div
              class={cn(
                'md-wrap min-w-0 rounded-[var(--radius-lg)] px-4 py-3 text-sm leading-relaxed [overflow-wrap:anywhere]',
                m.role === 'user' ? 'rounded-br-sm bg-surface-3 text-fg' : 'rounded-bl-sm border border-border bg-surface text-fg-dim',
                chip && 'border border-accent shadow-[inset_3px_0_0_var(--accent)]',
                solution &&
                  'border-[color-mix(in_oklab,var(--success)_50%,var(--border))] bg-[color-mix(in_oklab,var(--success)_5%,var(--surface))]'
              )}
              data-testid={chip ? 'attempt-message' : solution ? 'worked-solution' : undefined}
            >
              {#if solution}
                <p class="mb-2 flex items-center gap-1.5 text-xs font-medium text-success">
                  <svg viewBox="0 0 16 16" class="size-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"
                    ><rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 4.9-.7" stroke-linecap="round" /></svg
                  >{WORKED_SOLUTION_LABEL}
                </p>
              {:else if m.role === 'tutor'}
                <div class="eyebrow mb-1.5 !text-[0.55rem] text-accent">tutor</div>
              {:else if chip}
                <!-- The chip's tint sits on the plain surface, not the darker bubble, so its text keeps 4.5:1. -->
                <div class="mb-2 flex" aria-hidden="true" data-testid="attempt-chip">
                  <span class="rounded-full bg-surface"><Badge tone={chip.tone} dot>{chip.label}</Badge></span>
                </div>
                <span class="sr-only">Your attempt, {chip.status}: </span>
              {:else}
                <span class="sr-only">You: </span>
              {/if}
              {#if m.role === 'tutor'}
                <!-- Tutor replies: markdown, with line breaks and indentation kept. -->
                <Markdown text={m.content} pre />
              {:else}
                <!-- The learner's own words exactly as typed: maths like x**2 and pasted code stay literal. -->
                <span class="whitespace-pre-wrap" data-testid="learner-text">{m.content}</span>
              {/if}
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
    <Composer
      bind:this={composer}
      bind:value={input}
      disabled={busy || conceptId == null}
      attemptLogged={levels.attempt}
      {isMac}
      onsend={() => send()}
      onattempt={() => send(true)}
    />
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
      aria-label="Notes on {conceptName}"
      class="flex w-full min-w-0 flex-col gap-4 overflow-y-auto border-border px-6 py-5 lg:w-96 lg:shrink-0 lg:border-l lg:px-5"
    >
      <!-- One title: the editor's own "My notes on …" label heads the panel. -->
      {#if panelNotebook}
        {#key panelNotebook.concept_id}
          <NotesEditor
            conceptId={panelNotebook.concept_id}
            conceptName={panelNotebook.concept_name}
            saved={panelNotebook.note?.body ?? ''}
            savedAt={panelNotebook.note?.updated_at ?? null}
            vaultLockedNote={panelNotebook.vault_locked_note ?? null}
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
