import { describe, expect, it } from 'vitest';
import type { ConceptNote, NotebookItem } from './types';
import {
  NOTE_MAX_CHARS,
  NoteSaver,
  clearedSyncText,
  syncTargetText,
  draftStore,
  settledSave,
  trackSave,
  updateSyncTarget,
  SOURCE_LABEL,
  formatWhen,
  isSaveShortcut,
  itemHeading,
  noteStatus,
  notebookSections,
  sourceHref,
  storedVaultPath
} from './notebook';

const item = (over: Partial<NotebookItem>): NotebookItem => ({
  kind: 'attempt',
  id: 1,
  created_at: '2026-10-22T09:00:00',
  source: 'tutor',
  text: 't',
  conversation_id: 3,
  accepted: true,
  assessment_kind: null,
  label: '',
  prompt: '',
  score: null,
  verdict: '',
  gaps: [],
  ...over
});

describe('notebook sections', () => {
  it('splits items by kind and keeps their order', () => {
    const items = [
      item({ id: 5, kind: 'explanation', source: 'teach' }),
      item({ id: 4, kind: 'solution' }),
      item({ id: 3 }),
      item({ id: 2, kind: 'explanation', source: 'assess' }),
      item({ id: 1, accepted: false })
    ];
    const s = notebookSections(items);
    expect(s.attempts.map((i) => i.id)).toEqual([3, 1]);
    expect(s.explanations.map((i) => i.id)).toEqual([5, 2]);
    expect(s.solutions.map((i) => i.id)).toEqual([4]);
  });
});

describe('where an item came from', () => {
  it('links back to the page it was made on', () => {
    expect(sourceHref(item({ source: 'tutor' }), 7, 9)).toBe('/topics/7/tutor?concept=9');
    expect(sourceHref(item({ source: 'assess' }), 7, 9)).toBe('/topics/7/assess');
    expect(sourceHref(item({ source: 'teach' }), 7, 9)).toBe('/topics/7/teach');
    expect(sourceHref(item({ source: 'retention' }), 7, 9)).toBe('/topics/7/retention');
    expect(SOURCE_LABEL.retention).toBe('Retention');
  });

  it('names each item plainly', () => {
    expect(itemHeading(item({ accepted: true }))).toBe('Attempt, accepted');
    expect(itemHeading(item({ accepted: false }))).toBe('Attempt, not accepted');
    expect(itemHeading(item({ kind: 'explanation', label: 'Teach-back', score: 0.625 }))).toBe('Teach-back, 63 of 100');
    expect(itemHeading(item({ kind: 'solution' }))).toBe('Worked solution');
  });
});

describe('note status', () => {
  it('says whether the note is saved', () => {
    expect(noteStatus({ saved: 'a', draft: 'a', saving: false, error: '', savedAt: null }).text).toBe('No notes yet');
    expect(noteStatus({ saved: 'a', draft: 'a', saving: false, error: '', savedAt: '2026-10-22T09:00:00' }).text).toBe('Saved');
    expect(noteStatus({ saved: 'a', draft: 'b', saving: false, error: '', savedAt: null })).toEqual({
      state: 'unsaved',
      text: 'Unsaved changes'
    });
    expect(noteStatus({ saved: 'a', draft: 'b', saving: true, error: '', savedAt: null }).text).toBe('Saving');
    expect(noteStatus({ saved: 'a', draft: 'b', saving: false, error: 'too long', savedAt: null })).toEqual({
      state: 'error',
      text: 'Not saved: too long'
    });
  });

  it('flags a note over the limit before it is sent', () => {
    const big = 'x'.repeat(NOTE_MAX_CHARS + 1);
    const s = noteStatus({ saved: '', draft: big, saving: false, error: '', savedAt: null });
    expect(s.state).toBe('too_long');
    expect(s.text).toMatch(/50,000/);
  });

  it('uses plain words: no em dashes or exclamation marks', () => {
    const texts = [
      noteStatus({ saved: '', draft: 'x'.repeat(NOTE_MAX_CHARS + 1), saving: false, error: '', savedAt: null }).text,
      noteStatus({ saved: 'a', draft: 'b', saving: false, error: '', savedAt: null }).text
    ];
    for (const t of texts) expect(t).not.toMatch(/[—–!]/);
  });
});

describe('save shortcut', () => {
  const key = (k: string, mods: Partial<Record<'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey', boolean>> = {}) => ({
    key: k,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    ...mods
  });
  it('is Ctrl+S or Cmd+S', () => {
    expect(isSaveShortcut(key('s', { ctrlKey: true }))).toBe(true);
    expect(isSaveShortcut(key('S', { metaKey: true }))).toBe(true);
    expect(isSaveShortcut(key('s'))).toBe(false);
    expect(isSaveShortcut(key('s', { ctrlKey: true, altKey: true }))).toBe(false);
  });
});

describe('formatWhen', () => {
  it('reads the API time as UTC and is empty for nothing', () => {
    expect(formatWhen(null)).toBe('');
    expect(formatWhen('not a date')).toBe('');
    expect(formatWhen('2026-10-22T09:00:00')).toMatch(/2026/);
  });
});

describe('storedVaultPath', () => {
  it('reads the vault page path, trimmed, and survives missing or blocked storage', () => {
    const data: Record<string, string> = {};
    const storage = { getItem: (k: string) => data[k] ?? null };
    expect(storedVaultPath(storage)).toBe('');
    data['aa_vault_path'] = '  /v  ';
    expect(storedVaultPath(storage)).toBe('/v');
    expect(
      storedVaultPath({
        getItem: () => {
          throw new Error('SecurityError');
        }
      })
    ).toBe('');
    expect(storedVaultPath(undefined)).toBe('');
  });
});

describe('drafts kept in this tab', () => {
  const memory = () => {
    const data: Record<string, string> = {};
    return {
      data,
      getItem: (k: string) => data[k] ?? null,
      setItem: (k: string, v: string) => void (data[k] = v),
      removeItem: (k: string) => void delete data[k]
    };
  };

  it('keeps a draft per concept until it is cleared', () => {
    const drafts = draftStore(memory());
    expect(drafts.get(3)).toBeNull();
    drafts.set(3, 'half written');
    drafts.set(4, 'other');
    expect(drafts.get(3)).toBe('half written');
    drafts.clear(3);
    expect(drafts.get(3)).toBeNull();
    expect(drafts.get(4)).toBe('other');
  });

  it('clears only the body that was saved, never a newer draft', () => {
    const drafts = draftStore(memory());
    drafts.set(3, 'newer');
    drafts.clear(3, 'older');
    expect(drafts.get(3)).toBe('newer');
    drafts.clear(3, 'newer');
    expect(drafts.get(3)).toBeNull();
  });

  it('works without storage, or with storage that throws', () => {
    const blocked = () => {
      throw new Error('blocked');
    };
    const throwing = { getItem: blocked, setItem: blocked, removeItem: blocked };
    for (const s of [throwing, null]) {
      const drafts = draftStore(s);
      expect(() => drafts.set(1, 'x')).not.toThrow();
      expect(drafts.get(1)).toBeNull();
      expect(() => drafts.clear(1)).not.toThrow();
    }
  });
});

describe('NoteSaver', () => {
  function deferred() {
    let resolve!: (v: ConceptNote) => void;
    const promise = new Promise<ConceptNote>((res) => {
      resolve = res;
    });
    return { promise, resolve };
  }
  const note = (body: string): ConceptNote => ({ concept_id: 1, body, updated_at: '2026-10-22T09:00:00' });
  const tick = async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve();
  };

  it('sends edits made during a save right after it, newest only', async () => {
    const sent: string[] = [];
    const calls: ReturnType<typeof deferred>[] = [];
    const saver = new NoteSaver((body) => {
      sent.push(body);
      const d = deferred();
      calls.push(d);
      return d.promise;
    });
    const first = saver.save('a');
    expect(saver.busy).toBe(true);
    const second = saver.save('ab');
    const third = saver.save('abc');
    expect(sent).toEqual(['a']);
    calls[0].resolve(note('a'));
    expect((await first).body).toBe('a');
    await tick();
    expect(sent).toEqual(['a', 'abc']);
    calls[1].resolve(note('abc'));
    expect((await second).body).toBe('abc');
    expect((await third).body).toBe('abc');
    expect(saver.busy).toBe(false);
  });

  it('still sends the queued edit when the running save fails', async () => {
    const sent: string[] = [];
    let n = 0;
    const saver = new NoteSaver(async (body) => {
      sent.push(body);
      if (n++ === 0) throw new Error('offline');
      return note(body);
    });
    const first = saver.save('a');
    const second = saver.save('ab');
    await expect(first).rejects.toThrow('offline');
    expect((await second).body).toBe('ab');
    expect(sent).toEqual(['a', 'ab']);
  });
});

describe('pending saves per concept', () => {
  it('lets a load wait for the save still on its way', async () => {
    let finish!: () => void;
    const save = new Promise<void>((res) => (finish = res));
    trackSave(9, save);
    let loaded = false;
    const load = settledSave(9).then(() => (loaded = true));
    await Promise.resolve();
    expect(loaded).toBe(false);
    finish();
    await load;
    expect(loaded).toBe(true);
  });

  it('does not wait on a failed save or another concept', async () => {
    trackSave(10, Promise.reject(new Error('x')));
    await expect(settledSave(10)).resolves.toBeUndefined();
    await expect(settledSave(11)).resolves.toBeUndefined();
  });
});

describe('updateSyncTarget', () => {
  it('stops syncing when the field is cleared, and registers a readable folder', async () => {
    const calls: string[] = [];
    const sync = async (p: string) => {
      calls.push(p);
      return { path: p, last_synced_at: null, last_error: '', last_error_at: null, problems: 0, pending: 0 };
    };
    expect((await updateSyncTarget(sync, '   ', false))?.path).toBe('');
    expect(await updateSyncTarget(sync, '/not/a/folder', false)).toBeNull();
    expect((await updateSyncTarget(sync, ' /vault ', true))?.path).toBe('/vault');
    expect(calls).toEqual(['', '/vault']);
  });
});

describe('what the Vault page says about notebook sync', () => {
  it('names the env vault and how to really turn it off', () => {
    const env = { path: '/vault', source: 'env' as const };
    expect(syncTargetText(env)).toBe(
      'Notes sync to /vault (set by AA_OBSIDIAN_VAULT_PATH). To stop, leave it empty in .env and restart.'
    );
    // Clearing the field never claims syncing stopped while the env vault is in effect.
    expect(clearedSyncText(env)).toBe(syncTargetText(env));
    expect(clearedSyncText(env)).not.toMatch(/no longer/);
  });

  it('says syncing stopped only when nothing is left to sync to', () => {
    expect(clearedSyncText({ path: '', source: '' })).toBe('Notebooks no longer sync to a vault set in this browser.');
    expect(clearedSyncText(null)).toMatch(/no longer/);
    expect(syncTargetText({ path: '/v', source: 'browser' })).toMatch(/^Notes sync to \/v:/);
    expect(syncTargetText(null)).toMatch(/do not sync/);
  });

  it('uses plain words', () => {
    for (const t of [
      syncTargetText({ path: '/v', source: 'env' }),
      syncTargetText({ path: '/v', source: 'browser' }),
      syncTargetText(null),
      clearedSyncText(null)
    ]) {
      expect(t).not.toMatch(/[—–!]/);
    }
  });
});
