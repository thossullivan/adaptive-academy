<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { beforeNavigate } from '$app/navigation';
  import { NoteConflictError, api } from '$lib/api';
  import { toasts } from '$lib/toast.svelte';
  import {
    NOTE_MAX_CHARS,
    NoteSaver,
    draftRestore,
    draftStore,
    formatWhen,
    isSaveShortcut,
    noteStatus,
    showDiscard,
    storedVaultPath,
    trackSave,
    type KeptDraft
  } from '$lib/notebook';
  import type { ConceptNote } from '$lib/types';
  import { cn } from '$lib/utils';
  import Button from './Button.svelte';
  import LiveStatus from './LiveStatus.svelte';

  // My notes on one concept: edit, then Save (or Ctrl/Cmd+S). Key the component on the
  // concept id: it starts from `saved` and keeps its own draft. The draft is also kept in
  // this tab (sessionStorage) until a save is confirmed, and restored here on the next visit,
  // so a failed save or a draft over the limit is never lost. A restored draft is saved only
  // once the learner edits it, keeps it, or presses Save, and when the saved note changed
  // after the draft was written, the learner picks which one to keep. Discard draft goes back
  // to the saved note. Edits made while a save runs are saved right after it. Leaving with
  // unsaved changes saves them on the way out; a reload, or leaving the page with a draft over
  // the limit, asks first. Every save sends the saved note it was written on; when another
  // tab or window saved first, the API refuses it (409) and the same choice is offered: keep
  // my draft (saved over the newer note) or use the saved note. Discard draft is offered only
  // for a restored draft or after such a refusal, never for ordinary typing.
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
  // The saved note's version as the server last told this editor: every save is sent on it,
  // and it moves on as each save lands (before a queued save goes out).
  let serverAt: string | null = untrack(() => savedAt);
  // A save queued behind one the API refused must not go out on the newer version unasked.
  class ChoicePending extends Error {}
  const saver = new NoteSaver(async (body: string) => {
    if (conflict) throw new ChoicePending('waiting for keep my draft or use the saved note');
    const note = await api.saveNote(id, body, storedVaultPath(), serverAt);
    serverAt = note.updated_at;
    return note;
  });

  let base = $state(untrack(() => saved));
  let at = $state<string | null>(untrack(() => savedAt));
  // A draft this tab kept from an earlier visit (a save that failed, or one never made).
  // Restored as it was when it was written on the note saved now; when the saved note has
  // changed since, restored too, but the learner picks which to keep (draftRestore).
  const kept = drafts.get(id);
  const restore = draftRestore(kept, untrack(() => saved), untrack(() => savedAt));
  const restored = restore !== 'none';
  let conflict = $state(restore === 'conflict');
  // Why the choice is offered: a restored draft whose note changed, or a save refused
  // because the note was saved elsewhere while this one was open.
  let conflictKind = $state<'restored' | 'saved-elsewhere'>('restored');
  // The saved note a kept draft was written on, kept with it until the conflict is settled.
  let keptBase = $state(kept?.base);
  // Discard draft is for a draft the learner didn't just type (see showDiscard).
  let offerDiscard = $state(restore !== 'none');
  // A restored draft is saved on the way out only once the learner edits it or keeps it.
  let touched = $state(!restored);
  let draft = $state(restored ? (kept as KeptDraft).body : untrack(() => saved));
  let saving = $state(false);
  let error = $state('');
  let box: HTMLTextAreaElement | null = null;
  let announce = $state(
    restore === 'conflict'
      ? `Restored a draft of your notes on ${name}, but the saved note changed after it. Keep your draft or use the saved note.`
      : restored
        ? `Restored your unsaved notes on ${name}.`
        : ''
  );

  const status = $derived(noteStatus({ saved: base, draft, saving, error, savedAt: at }));
  const changed = $derived(draft !== base);
  const tooLong = $derived(draft.length > NOTE_MAX_CHARS);
  const nearLimit = $derived(draft.length > NOTE_MAX_CHARS * 0.9);
  $effect(() => {
    dirty = changed;
  });
  // Keep the draft in this tab until what is shown is what was saved. While a conflict is
  // open the draft keeps the saved note it was written on, so it stays a conflict.
  $effect(() => {
    if (changed) drafts.set(id, draft, conflict ? keptBase : at);
    else drafts.clear(id);
  });

  /** Keep my draft: it replaces the saved note when saved, or on the way out. */
  function keepDraft() {
    const refused = conflictKind === 'saved-elsewhere';
    conflict = false;
    touched = true;
    announce = `Keeping your draft of the notes on ${name}. Save it to replace the saved note.`;
    box?.focus(); // the buttons are gone: carry on in the box
    // A refused save is sent again, now on the note saved elsewhere.
    if (refused) save();
  }

  /** Use the saved note, or Discard draft: back to what is saved, and the draft is gone. */
  function discardDraft(message = `Draft discarded. Showing your saved notes on ${name}.`) {
    conflict = false;
    touched = true;
    offerDiscard = false;
    draft = base;
    error = '';
    drafts.clear(id);
    announce = message;
    box?.focus();
  }

  /** Another tab or window saved the note first: show what is saved now and let the learner
   *  choose. The draft stays in the box (and in this tab) until they do. */
  function savedElsewhere(note: ConceptNote | null) {
    keptBase = at; // the version this draft was written on
    base = note?.body ?? '';
    at = note?.updated_at ?? null;
    serverAt = at;
    conflictKind = 'saved-elsewhere';
    conflict = true;
    offerDiscard = true;
    announce = `Your notes on ${name} were saved in another tab or window. Keep your draft or use the saved note.`;
  }

  function send(body: string): Promise<ConceptNote> {
    return trackSave(id, saver.save(body));
  }

  export async function save(): Promise<boolean> {
    if (!changed || tooLong) return !changed;
    const body = draft;
    // Saving is choosing the draft.
    conflict = false;
    touched = true;
    saving = true;
    error = '';
    try {
      const note = await send(body);
      // Edits typed meanwhile were saved after this one: the newest saved body is kept.
      base = note.body;
      at = note.updated_at;
      offerDiscard = false;
      announce = `Notes on ${name} saved.`;
      onsaved?.(note);
      return true;
    } catch (e) {
      if (e instanceof NoteConflictError) {
        savedElsewhere(e.note);
        return false;
      }
      if (e instanceof ChoicePending) return false; // the choice above decides
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
    // Editing a restored draft is working on it: it is kept, and saved on the way out.
    touched = true;
    conflict = false;
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
  // A restored draft the learner hasn't edited or chosen to keep is not saved: it stays in the
  // tab, and comes back (and asks again) next time.
  onDestroy(() => {
    if (!changed || !touched) return;
    if (tooLong) {
      toasts.show(`Your notes on ${name} are over the limit and were not saved. The draft is kept in this tab.`, 'error', 9000);
      return;
    }
    // The learner left without choosing between their draft and the note saved elsewhere:
    // nothing is sent, and the draft (kept with its version) asks again next time.
    if (conflict) {
      toasts.show(`Your draft of your notes on ${name} is kept in this tab. Choose which version to keep next time.`, 'error', 9000);
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
  {#if conflict}
    <div
      id="{uid}-conflict"
      class="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-[color-mix(in_oklab,var(--warn)_45%,transparent)] bg-[color-mix(in_oklab,var(--warn)_8%,transparent)] px-3 py-2.5"
      data-testid="note-conflict"
    >
      <p class="text-xs leading-relaxed text-fg-dim">
        {#if conflictKind === 'saved-elsewhere'}
          Your notes were saved in another tab or window while you were editing{at ? ` (saved ${formatWhen(at)})` : ''}.
          Your draft was not saved. Which one do you want?
        {:else}
          This is a draft kept in this tab, but your saved notes changed after it{at ? ` (saved ${formatWhen(at)})` : ''}.
          Which one do you want?
        {/if}
      </p>
      <div class="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onclick={keepDraft}>Keep my draft</Button>
        <Button
          size="sm"
          variant="outline"
          onclick={() => discardDraft(`Showing your saved notes on ${name}. The draft is discarded.`)}>Use the saved note</Button
        >
      </div>
    </div>
  {/if}
  <textarea
    id="{uid}-notes"
    bind:this={box}
    bind:value={draft}
    {rows}
    {onkeydown}
    {oninput}
    aria-describedby="{conflict ? `${uid}-conflict ` : ''}{uid}-help {uid}-status"
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
    <div class="flex flex-wrap items-center gap-2">
      {#if showDiscard({ offer: offerDiscard, changed, conflict, saving })}
        <Button size="sm" variant="ghost" onclick={() => discardDraft()}>Discard draft</Button>
      {/if}
      <Button size="sm" onclick={save} disabled={!changed || tooLong}>
        {saving ? 'Saving…' : 'Save notes'}
      </Button>
    </div>
  </div>
  <p id="{uid}-help" class="text-xs text-muted">
    Ctrl+S or Cmd+S saves. When a vault is set on the Vault page, your notes and work also go into this concept's note
    there.
  </p>
  <LiveStatus message={announce} />
</div>
