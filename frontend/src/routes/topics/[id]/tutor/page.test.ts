import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Composer from './Composer.svelte';
import { ATTEMPT_NOTES, attemptNote, attemptShortcutLabel, composerAction } from './attempt';

const key = (k: string, mods: Partial<Record<'shiftKey' | 'ctrlKey' | 'metaKey' | 'altKey' | 'isComposing', boolean>> = {}) => ({
  key: k,
  shiftKey: false,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  isComposing: false,
  ...mods
});

describe('composer keyboard shortcuts', () => {
  it('sends on Enter', () => {
    expect(composerAction(key('Enter'))).toBe('send');
  });

  it('submits an attempt on Ctrl+Enter or Cmd+Enter', () => {
    expect(composerAction(key('Enter', { ctrlKey: true }))).toBe('attempt');
    expect(composerAction(key('Enter', { metaKey: true }))).toBe('attempt');
  });

  it('leaves Shift+Enter, other keys, and IME composition alone', () => {
    expect(composerAction(key('Enter', { shiftKey: true }))).toBeNull();
    expect(composerAction(key('Enter', { altKey: true }))).toBeNull();
    expect(composerAction(key('Enter', { isComposing: true }))).toBeNull();
    expect(composerAction(key('a'))).toBeNull();
  });

  it('names the shortcut for the platform', () => {
    expect(attemptShortcutLabel(true)).toBe('⌘ Enter');
    expect(attemptShortcutLabel(false)).toBe('Ctrl+Enter');
  });
});

describe('attempt notes', () => {
  it('has a kind note for an attempt that was not logged, and none otherwise', () => {
    expect(attemptNote('rejected')).toBe('Not logged as an attempt yet. Add your reasoning or a first step, then submit again.');
    expect(attemptNote('unverified')).toMatch(/couldn't be checked/);
    expect(attemptNote('accepted')).toBeNull();
    expect(attemptNote('already_logged')).toBeNull();
    expect(attemptNote(null)).toBeNull();
    expect(attemptNote(undefined)).toBeNull();
  });

  it('uses plain words: no em dashes or exclamation marks', () => {
    for (const note of Object.values(ATTEMPT_NOTES)) {
      expect(note).not.toMatch(/[—–!]/);
    }
  });
});

describe('Composer', () => {
  const props = { value: '', disabled: false, onsend: () => {}, onattempt: () => {} };

  it('renders both actions with their shortcuts and a described attempt button', () => {
    const { body } = render(Composer, { props: { ...props, value: 'my attempt' } });

    expect(body).toContain('aria-label="Message the tutor"');
    expect(body).toMatch(/<button[^>]*aria-keyshortcuts="Enter"[^>]*>(?:\s|<!--[^>]*-->)*Send/);
    expect(body).toMatch(/<button[^>]*aria-keyshortcuts="Control\+Enter Meta\+Enter"[^>]*>(?:\s|<!--[^>]*-->)*Submit attempt/);
    expect(body).toContain('aria-describedby="tutor-composer-hint"');
    expect(body).toContain('id="tutor-composer-hint"');
    expect(body).toContain('Ctrl+Enter');
    expect(body).not.toMatch(/<button[^>]*\sdisabled(=""|[\s>])/);
  });

  it('shows the Mac shortcut on a Mac', () => {
    const { body } = render(Composer, { props: { ...props, value: 'x', isMac: true } });
    expect(body).toContain('⌘ Enter');
  });

  it('disables both actions while the message is empty or the composer is busy', () => {
    const empty = render(Composer, { props: { ...props, value: '   ' } }).body;
    expect(empty.match(/<button[^>]*\sdisabled(=""|[\s>])/g)).toHaveLength(2);
    const busy = render(Composer, { props: { ...props, value: 'x', disabled: true } }).body;
    expect(busy.match(/<button[^>]*\sdisabled(=""|[\s>])/g)).toHaveLength(2);
    expect(busy).toMatch(/<textarea[^>]*\sdisabled(=""|[\s>])/);
  });
});
