<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { beforeNavigate } from '$app/navigation';
  import { api } from '$lib/api';
  import { toasts } from '$lib/toast.svelte';
  import {
    NOTE_MAX_CHARS,
    NoteSaver,
    draftStore,
    formatWhen,
    isSaveShortcut,
    noteStatus,
    storedVaultPath,
    trackSave
  } from '$lib/notebook';
  import type { ConceptNote } from '$lib/types';
  import { cn } from '$lib/utils';
  import Button from './Button.svelte';
  import LiveStatus from './LiveStatus.svelte';

  // My notes on one concept: edit, then Save (or Ctrl/Cmd+S). Key the component on the
  // concept id: it starts from `saved` and keeps its own draft. The draft is also kept in
  // this tab (sessionStorage) until a save is confirmed, and restored here on the next visit,
  // so a failed save or a draft over the limit is never lost. Edits made while a save runs
  // are saved right after it. Leaving with unsaved changes saves them on the way out; a
  // reload, or leaving the page with a draft over the limit, asks first.
  let {
    conceptId,
    conceptName,
    saved = '',
    savedAt = null,
    rows = 8,
    dirty = $bindable(false),
    onsaved,
    class: klass = ''
  }: {
    conceptId: number;
    conceptName: string;
    saved?: string;
    savedAt?: string | null;
    rows?: number;
    dirty?: boolean;
    onsaved?: (note: ConceptNote) => void;
    class?: string;
  } = $props();

  const uid = $props.id();
  const drafts = draftStore();
  const id = untrack(() => conceptId);
  const name = untrack(() => conceptName);
  const saver = new NoteSaver((body: string) => api.saveNote(id, body, storedVaultPath()));

  let base = $state(untrack(() => saved));
  let at = $state<string | null>(untrack(() => savedAt));
  // A draft this tab kept from an earlier visit (a save that failed, or one never made).
  const kept = drafts.get(id);
  const restored = kept !== null && kept !== untrack(() => saved);
  let draft = $state(restored ? (kept as string) : untrack(() => saved));
  let saving = $state(false);
  let error = $state('');
  let announce = $state(restored ? `Restored your unsaved notes on ${name}.` : '');

  const status = $derived(noteStatus({ saved: base, draft, saving, error, savedAt: at }));
  const changed = $derived(draft !== base);
  const tooLong = $derived(draft.length > NOTE_MAX_CHARS);
  const nearLimit = $derived(draft.length > NOTE_MAX_CHARS * 0.9);
  $effect(() => {
    dirty = changed;
  });
  // Keep the draft in this tab until what is shown is what was saved.
  $effect(() => {
    if (changed) drafts.set(id, draft);
    else drafts.clear(id);
  });

  function send(body: string): Promise<ConceptNote> {
    return trackSave(id, saver.save(body));
  }

  export async function save(): Promise<boolean> {
    if (!changed || tooLong) return !changed;
    const body = draft;
    saving = true;
    error = '';
    try {
      const note = await send(body);
      // Edits typed meanwhile were saved after this one: the newest saved body is kept.
      base = note.body;
      at = note.updated_at;
      announce = `Notes on ${name} saved.`;
      onsaved?.(note);
      return true;
    } catch (e) {
      if (draft === body) {
        error = e instanceof Error ? e.message : String(e);
        announce = `Notes not saved. ${error}`;
      }
      return false;
    } finally {
      saving = saver.busy;
    }
  }

  function onkeydown(e: KeyboardEvent) {
    if (!isSaveShortcut(e)) return;
    e.preventDefault();
    save();
  }

  function oninput() {
    error = '';
  }

  // A reload or closing the tab: let the browser ask first (the draft is also kept in the tab).
  $effect(() => {
    if (!changed) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  });

  // A draft over the limit can't be saved on the way out: ask before leaving the page.
  beforeNavigate((nav) => {
    if (!tooLong || nav.willUnload) return;
    const leave = window.confirm(
      `Your notes on ${name} are over the ${NOTE_MAX_CHARS.toLocaleString('en-US')} character limit, so they can't be saved. Leave anyway? The draft stays in this tab.`
    );
    if (!leave) nav.cancel();
  });

  // Leaving the concept or the page: unsaved changes are saved on the way out. If that fails,
  // or the draft is over the limit, the draft stays in this tab and comes back next time.
  onDestroy(() => {
    if (!changed) return;
    if (tooLong) {
      toasts.show(`Your notes on ${name} are over the limit and were not saved. The draft is kept in this tab.`, 'error', 9000);
      return;
    }
    const body = draft;
    send(body)
      .then(() => {
        drafts.clear(id, body);
        toasts.show(`Saved your notes on ${name}.`);
      })
      .catch((e) =>
        toasts.show(
          `Your notes on ${name} were not saved. ${e instanceof Error ? e.message : e} The draft is kept in this tab.`,
          'error',
          9000
        )
      );
  });

  const tone: Record<string, string> = {
    saved: 'text-muted',
    empty: 'text-muted',
    saving: 'text-muted',
    unsaved: 'text-warn',
    error: 'text-danger',
    too_long: 'text-danger'
  };
</script>

<div class={cn('flex flex-col gap-2', klass)}>
  <label for="{uid}-notes" class="text-sm font-medium text-fg">My notes on {conceptName}</label>
  <textarea
    id="{uid}-notes"
    bind:value={draft}
    {rows}
    {onkeydown}
    {oninput}
    aria-describedby="{uid}-help {uid}-status"
    aria-keyshortcuts="Control+S Meta+S"
    placeholder="Your own words: what clicked, what to check, questions for next time."
    class="w-full resize-y rounded-[var(--radius-sm)] border border-control-border bg-surface-2 px-3 py-2.5 text-sm leading-relaxed text-fg placeholder:text-faint transition-colors hover:border-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
  ></textarea>
  <div class="flex flex-wrap items-center justify-between gap-2">
    <p id="{uid}-status" class={cn('text-xs', tone[status.state])} data-testid="note-status" data-state={status.state}>
      {status.text}{#if status.state === 'saved' && at}<span class="text-faint">{` · ${formatWhen(at)}`}</span>{/if}
      {#if nearLimit && status.state !== 'too_long'}
        <span class="text-faint">{` · ${draft.length.toLocaleString('en-US')} of ${NOTE_MAX_CHARS.toLocaleString('en-US')} characters`}</span>
      {/if}
      {#if restored && changed}<span class="text-faint" data-testid="note-restored">{' · restored from this tab'}</span>{/if}
    </p>
    <Button size="sm" onclick={save} disabled={!changed || tooLong}>
      {saving ? 'Saving…' : 'Save notes'}
    </Button>
  </div>
  <p id="{uid}-help" class="text-xs text-muted">
    Ctrl+S or Cmd+S saves. When a vault is set on the Vault page, your notes and work also go into this concept's note
    there.
  </p>
  <LiveStatus message={announce} />
</div>
