import { describe, expect, it } from 'vitest';
import type { NotebookItem } from './types';
import {
  NOTE_MAX_CHARS,
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
