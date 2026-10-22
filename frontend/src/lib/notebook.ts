// Concept notebook helpers: a concept's notes and work in one place (GET /api/concepts/{id}/notebook).

import type { NotebookItem, NotebookSource } from './types';

/** Mirrors engine/notebook.py NOTE_MAX_CHARS (tests/test_frontend_constants.py keeps them equal). */
export const NOTE_MAX_CHARS = 50000;

/** The vault page remembers its path under this key (this browser only). */
export const VAULT_PATH_KEY = 'aa_vault_path';

export const SOURCE_LABEL: Record<NotebookSource, string> = {
  tutor: 'Tutor',
  assess: 'Assess',
  teach: 'Teach',
  retention: 'Retention'
};

/** The page an item was made on. Tutor links open that concept's tutor. */
export function sourceHref(item: Pick<NotebookItem, 'source'>, topicId: number, conceptId: number): string {
  if (item.source === 'tutor') return `/topics/${topicId}/tutor?concept=${conceptId}`;
  return `/topics/${topicId}/${item.source}`;
}

export function notebookSections(items: NotebookItem[]) {
  return {
    attempts: items.filter((i) => i.kind === 'attempt'),
    explanations: items.filter((i) => i.kind === 'explanation'),
    solutions: items.filter((i) => i.kind === 'solution')
  };
}

/** One plain line naming the item. */
export function itemHeading(item: NotebookItem): string {
  if (item.kind === 'attempt') return item.accepted ? 'Attempt, accepted' : 'Attempt, not accepted';
  if (item.kind === 'solution') return 'Worked solution';
  const score = item.score == null ? '' : `, ${Math.round(item.score * 100)} of 100`;
  return `${item.label || 'Explanation'}${score}`;
}

export type NoteState = 'empty' | 'saved' | 'unsaved' | 'saving' | 'error' | 'too_long';

/** Whether My notes are saved, in words for the status line next to Save. */
export function noteStatus(s: {
  saved: string;
  draft: string;
  saving: boolean;
  error: string;
  savedAt: string | null;
}): { state: NoteState; text: string } {
  if (s.draft.length > NOTE_MAX_CHARS) {
    return {
      state: 'too_long',
      text: `Too long to save: ${s.draft.length.toLocaleString('en-US')} of ${NOTE_MAX_CHARS.toLocaleString('en-US')} characters`
    };
  }
  if (s.saving) return { state: 'saving', text: 'Saving' };
  if (s.error) return { state: 'error', text: `Not saved: ${s.error}` };
  if (s.draft !== s.saved) return { state: 'unsaved', text: 'Unsaved changes' };
  if (!s.savedAt) return { state: 'empty', text: 'No notes yet' };
  return { state: 'saved', text: 'Saved' };
}

/** Ctrl+S or Cmd+S (no Alt): save the note instead of the page. */
export function isSaveShortcut(e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean }): boolean {
  return (e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 's';
}

// The API serializes SQLite's naive UTC datetimes without an offset; read them as UTC.
const utc = (iso: string) => (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);

/** A local date and time for an item, or '' when there is none. */
export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return '';
  const t = Date.parse(utc(iso));
  if (Number.isNaN(t)) return '';
  return new Date(t).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

type StorageLike = { getItem(key: string): string | null };

/** The vault path the Vault page saved in this browser, or ''. Never throws (storage can be
 *  blocked). `storage` defaults to the browser's localStorage. */
export function storedVaultPath(storage?: StorageLike | null): string {
  try {
    const from = storage === undefined ? (typeof window === 'undefined' ? null : window.localStorage) : storage;
    return (from?.getItem(VAULT_PATH_KEY) ?? '').trim();
  } catch {
    return '';
  }
}
