// Concept notebook helpers: a concept's notes and work in one place (GET /api/concepts/{id}/notebook).

import type { ConceptNote, NotebookItem, NotebookSource, VaultSync } from './types';

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

// --- Keeping drafts safe -----------------------------------------------------------------

type DraftStorage = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

const DRAFT_PREFIX = 'aa.note-draft.';

/** Unsaved notes per concept, kept in this tab (sessionStorage) until a save is confirmed,
 *  so a failed save, a draft over the limit, or a switch away never loses them. Never throws:
 *  without storage, drafts simply aren't kept. `storage` defaults to sessionStorage. */
export function draftStore(storage?: DraftStorage | null) {
  const from = (): DraftStorage | null => {
    if (storage !== undefined) return storage;
    return typeof window === 'undefined' ? null : window.sessionStorage;
  };
  return {
    get(conceptId: number): string | null {
      try {
        return from()?.getItem(DRAFT_PREFIX + conceptId) ?? null;
      } catch {
        return null;
      }
    },
    set(conceptId: number, body: string): void {
      try {
        from()?.setItem(DRAFT_PREFIX + conceptId, body);
      } catch {
        /* storage full or blocked: the draft lives only on the page */
      }
    },
    /** Forget the draft; with `ifBody`, only when it is that body (a newer one stays). */
    clear(conceptId: number, ifBody?: string): void {
      try {
        const s = from();
        if (!s) return;
        if (ifBody !== undefined && s.getItem(DRAFT_PREFIX + conceptId) !== ifBody) return;
        s.removeItem(DRAFT_PREFIX + conceptId);
      } catch {
        /* nothing to clear */
      }
    }
  };
}

/** One concept's saves, one at a time: an edit saved while a save is running is sent right
 *  after it (only the newest such edit), so nothing typed meanwhile is lost or reordered. */
export class NoteSaver<T = ConceptNote> {
  private running: Promise<T> | null = null;
  private queued: string | null = null;
  private next: Promise<T> | null = null;

  constructor(private send: (body: string) => Promise<T>) {}

  get busy(): boolean {
    return this.running !== null || this.next !== null;
  }

  save(body: string): Promise<T> {
    if (this.running) {
      this.queued = body;
      this.next ??= this.running
        .catch(() => undefined)
        .then(() => {
          const queued = this.queued as string;
          this.queued = null;
          this.next = null;
          return this.save(queued);
        });
      return this.next;
    }
    const run = this.send(body).finally(() => {
      if (this.running === run) this.running = null;
    });
    this.running = run;
    return run;
  }
}

// Saves still on their way, per concept: a load waits for them, so it never shows text older
// than what was just saved (and the next save never overwrites the newer text with it).
const pendingSaves = new Map<number, Promise<void>>();

export function trackSave<T>(conceptId: number, save: Promise<T>): Promise<T> {
  const settled = save.then(
    () => undefined,
    () => undefined
  );
  pendingSaves.set(conceptId, settled);
  settled.then(() => {
    if (pendingSaves.get(conceptId) === settled) pendingSaves.delete(conceptId);
  });
  return save;
}

/** Resolves once every save tracked for this concept has finished (failed ones too). */
export async function settledSave(conceptId: number): Promise<void> {
  let pending = pendingSaves.get(conceptId);
  while (pending) {
    await pending;
    const later = pendingSaves.get(conceptId);
    pending = later === pending ? undefined : later;
  }
}

/** The Vault page's folder decides where notebooks sync: an empty field stops syncing to a
 *  browser-set vault, a readable folder becomes the target, anything else changes nothing. */
export async function updateSyncTarget<T>(
  vaultSync: (path: string) => Promise<T>,
  path: string,
  isDir: boolean
): Promise<T | null> {
  const p = path.trim();
  if (!p) return vaultSync('');
  return isDir ? vaultSync(p) : null;
}

/** What the Vault page says about notebook sync. Honest about AA_OBSIDIAN_VAULT_PATH: only
 *  .env turns that vault off, so clearing the field never "stops" it. */
export function syncTargetText(sync: Pick<VaultSync, 'path' | 'source'> | null): string {
  if (!sync?.path) return 'Notebooks do not sync to a vault. Check a vault folder above to start.';
  if (sync.source === 'env') {
    return `Notes sync to ${sync.path} (set by AA_OBSIDIAN_VAULT_PATH). To stop, leave it empty in .env and restart.`;
  }
  return `Notes sync to ${sync.path}: notes, attempts, explanations, and worked solutions go into each concept's note, between two marker lines. Everything else in the note stays yours.`;
}

/** What to announce after the field was cleared, given where sync points now. */
export function clearedSyncText(sync: Pick<VaultSync, 'path' | 'source'> | null): string {
  if (sync?.path && sync.source === 'env') return syncTargetText(sync);
  return 'Notebooks no longer sync to a vault set in this browser.';
}
