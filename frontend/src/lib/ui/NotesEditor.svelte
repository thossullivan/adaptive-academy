<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { api } from '$lib/api';
  import { toasts } from '$lib/toast.svelte';
  import { NOTE_MAX_CHARS, formatWhen, isSaveShortcut, noteStatus, storedVaultPath } from '$lib/notebook';
  import type { ConceptNote } from '$lib/types';
  import { cn } from '$lib/utils';
  import Button from './Button.svelte';
  import LiveStatus from './LiveStatus.svelte';

  // My notes on one concept: edit, then Save (or Ctrl/Cmd+S). Key the component on the
  // concept id: it starts from `saved` and keeps its own draft. Unsaved changes are saved
  // when it goes away (switching concept or page), and the browser warns before a reload.
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
  let base = $state(untrack(() => saved));
  let at = $state<string | null>(untrack(() => savedAt));
  let draft = $state(untrack(() => saved));
  let saving = $state(false);
  let error = $state('');
  let announce = $state('');

  const status = $derived(noteStatus({ saved: base, draft, saving, error, savedAt: at }));
  const changed = $derived(draft !== base);
  const nearLimit = $derived(draft.length > NOTE_MAX_CHARS * 0.9);
  $effect(() => {
    dirty = changed;
  });

  export async function save(): Promise<boolean> {
    if (saving || !changed || draft.length > NOTE_MAX_CHARS) return !changed;
    saving = true;
    error = '';
    const body = draft;
    try {
      const note = await api.saveNote(conceptId, body, storedVaultPath());
      base = note.body;
      at = note.updated_at;
      announce = `Notes on ${conceptName} saved.`;
      onsaved?.(note);
      return true;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      announce = `Notes not saved. ${error}`;
      return false;
    } finally {
      saving = false;
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

  // A reload or closing the tab would lose the draft: let the browser ask first.
  $effect(() => {
    if (!changed) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  });

  // Leaving the concept or the page keeps the draft: it is saved on the way out.
  onDestroy(() => {
    if (!changed || saving || draft.length > NOTE_MAX_CHARS) return;
    const name = conceptName;
    api
      .saveNote(conceptId, draft, storedVaultPath())
      .then(() => toasts.show(`Saved your notes on ${name}.`))
      .catch((e) => toasts.show(`Your notes on ${name} were not saved. ${e instanceof Error ? e.message : e}`, 'error', 9000));
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
    </p>
    <Button size="sm" onclick={save} disabled={saving || !changed || draft.length > NOTE_MAX_CHARS}>
      {saving ? 'Saving…' : 'Save notes'}
    </Button>
  </div>
  <p id="{uid}-help" class="text-xs text-muted">
    Ctrl+S or Cmd+S saves. When a vault is set on the Vault page, your notes and work also go into this concept's note
    there.
  </p>
  <LiveStatus message={announce} />
</div>
