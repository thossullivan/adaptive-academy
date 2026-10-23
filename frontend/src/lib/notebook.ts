// Concept notebook helpers: a concept's notes and work in one place (GET /api/concepts/{id}/notebook).

import type { ConceptNote, NotebookConcept, NotebookItem, NotebookSource, VaultSync } from './types';

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
  const { title, score } = itemHeadingParts(item);
  return score ? `${title}, ${score}` : title;
}

/** The heading in two parts, so the score can be shown in its level's colour. */
export function itemHeadingParts(item: NotebookItem): { title: string; score: string | null } {
  if (item.kind === 'attempt') return { title: item.accepted ? 'Attempt, accepted' : 'Attempt, not accepted', score: null };
  if (item.kind === 'solution') return { title: 'Worked solution', score: null };
  return {
    title: item.label || 'Explanation',
    score: item.score == null ? null : `${Math.round(item.score * 100)} of 100`
  };
}

/** The knowledge level a graded score maps to (mirrors engine/assess.py level_from_score:
 *  0.75 and up high, 0.45 and up medium, else low). Pair with utils levelColor. */
export function scoreLevel(score: number): 'high' | 'medium' | 'low' {
  return score >= 0.75 ? 'high' : score >= 0.45 ? 'medium' : 'low';
}

/** The concept the Notebook opens on without a ?concept=: the most recently active one with
 *  notes, else the most recently active one with any work. Null when the list is empty. */
export function defaultNotebookConcept(
  concepts: Pick<NotebookConcept, 'concept_id' | 'has_note' | 'last_activity_at'>[]
): number | null {
  const newest = [...concepts].sort((a, b) => Date.parse(utc(b.last_activity_at)) - Date.parse(utc(a.last_activity_at)));
  return (newest.find((c) => c.has_note) ?? newest[0])?.concept_id ?? null;
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

/** A kept draft and the saved note it was written on: that note's updated_at (null when
 *  there was no saved note yet; undefined when unknown, for a draft kept before this was
 *  recorded). */
export interface KeptDraft {
  body: string;
  base: string | null | undefined;
}

function parseDraft(raw: string | null): KeptDraft | null {
  if (raw === null) return null;
  try {
    const v = JSON.parse(raw);
    if (v && typeof v === 'object' && v.v === 1 && typeof v.body === 'string') {
      return { body: v.body, base: typeof v.base === 'string' ? v.base : v.base === null ? null : undefined };
    }
  } catch {
    /* an older plain-text draft */
  }
  return { body: raw, base: undefined };
}

/** Unsaved notes per concept, kept in this tab (sessionStorage) until a save is confirmed,
 *  so a failed save, a draft over the limit, or a switch away never loses them. Each draft
 *  records the saved note it was written on: a restored draft whose note changed since asks
 *  before it is kept (draftRestore). Overwrites between two open editors are caught by the
 *  API, not here: each save sends the version it was written on, and the API refuses (409)
 *  when another save came first (api.saveNote). Never throws: without storage, drafts simply
 *  aren't kept. `storage` defaults to sessionStorage. */
export function draftStore(storage?: DraftStorage | null) {
  const from = (): DraftStorage | null => {
    if (storage !== undefined) return storage;
    return typeof window === 'undefined' ? null : window.sessionStorage;
  };
  const read = (conceptId: number): KeptDraft | null => {
    try {
      return parseDraft(from()?.getItem(DRAFT_PREFIX + conceptId) ?? null);
    } catch {
      return null;
    }
  };
  return {
    get: read,
    /** Keep `body`, written on the saved note last updated at `base` (null: no note yet;
     *  left out: not known, so restoring it will ask). */
    set(conceptId: number, body: string, base?: string | null): void {
      try {
        from()?.setItem(DRAFT_PREFIX + conceptId, JSON.stringify({ v: 1, body, base }));
      } catch {
        /* storage full or blocked: the draft lives only on the page */
      }
    },
    /** Forget the draft; with `ifBody`, only when it is that body (a newer one stays). */
    clear(conceptId: number, ifBody?: string): void {
      try {
        const s = from();
        if (!s) return;
        if (ifBody !== undefined && read(conceptId)?.body !== ifBody) return;
        s.removeItem(DRAFT_PREFIX + conceptId);
      } catch {
        /* nothing to clear */
      }
    },
    /** Forget every draft for these concepts, whatever it says: for a deleted topic, whose
     *  concept ids the database hands out again (no AUTOINCREMENT), so an old draft would
     *  otherwise restore into a new topic's concept. */
    forget(conceptIds: Iterable<number>): void {
      for (const conceptId of conceptIds) {
        try {
          from()?.removeItem(DRAFT_PREFIX + conceptId);
        } catch {
          /* nothing to clear */
        }
      }
    }
  };
}

/** Whether the editor offers Discard draft. Only for a draft the learner didn't just type:
 *  one restored from this tab, or one left after a save was refused because the note was
 *  saved elsewhere. Ordinary live edits get no one-click wipe (there is no undo). */
export function showDiscard(s: { offer: boolean; changed: boolean; conflict: boolean; saving: boolean }): boolean {
  return s.offer && s.changed && !s.conflict && !s.saving;
}

/**
 * What to do with a draft this tab kept, given the saved note now on the server:
 * - 'none': there is no draft, or it says what the saved note says.
 * - 'restore': it was written on this very saved note: put it back as it was.
 * - 'conflict': the saved note changed after the draft was written (another tab, or the
 *   Obsidian sync): put it back, but ask which one to keep, and never save it on the way out
 *   unless the learner chooses it or edits it.
 */
export function draftRestore(
  kept: KeptDraft | null,
  saved: string,
  savedAt: string | null
): 'none' | 'restore' | 'conflict' {
  if (!kept || kept.body === saved) return 'none';
  return kept.base !== undefined && kept.base === savedAt ? 'restore' : 'conflict';
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

type SyncProblems = Pick<VaultSync, 'problems'> & Partial<Pick<VaultSync, 'last_error' | 'skipped_notes'>>;

/** The sync problems that are not about one note, told apart by their message
 *  (engine/notebook_sync.py, api/routes_notebook.py): a vault folder that can't be used,
 *  and a full sync queue. */
function otherProblem(lastError: string | undefined): 'vault' | 'queue' | null {
  if (lastError?.startsWith("Couldn't sync to the vault")) return 'vault';
  if (lastError?.startsWith('The vault sync queue is full')) return 'queue';
  return null;
}

/** How many notes the sync left out. `problems` also counts problems that are not about a
 *  note (the vault folder, the queue), so an API that sends `skipped_notes` is trusted; an
 *  older one only says how many problems there are, and the latest one's message tells
 *  whether one of them is not a note. */
export function skippedNotes(sync: SyncProblems): number {
  if (typeof sync.skipped_notes === 'number') return Math.max(0, sync.skipped_notes);
  const problems = sync.problems || 0;
  return Math.max(0, problems - (otherProblem(sync.last_error) ? 1 : 0));
}

/** When notes last synced, and whether that left notes out: never a bare "Last synced just
 *  now" beside a note the sync skipped (its section edited in Obsidian, say). A problem with
 *  the vault folder or the sync queue gets its own words, never "1 note skipped". */
export function lastSyncedText(sync: SyncProblems, ago: string): string {
  const skipped = skippedNotes(sync);
  if (skipped) {
    const notes = skipped === 1 ? '1 note' : `${skipped} notes`;
    return `Last synced ${ago}, with ${notes} skipped (see below).`;
  }
  if ((sync.problems || 0) <= 0) return `Last synced ${ago}.`;
  const other = otherProblem(sync.last_error);
  if (other === 'vault') return `Last synced ${ago}. Notes can't sync to this vault right now (see below).`;
  if (other === 'queue') return `Last synced ${ago}, but some note updates were skipped (see below).`;
  return `Last synced ${ago}, with a sync problem (see below).`;
}

/** What to announce after the field was cleared, given where sync points now. */
export function clearedSyncText(sync: Pick<VaultSync, 'path' | 'source'> | null): string {
  if (sync?.path && sync.source === 'env') return syncTargetText(sync);
  return 'Notebooks no longer sync to a vault set in this browser.';
}
