import { render } from 'svelte/server';
import { describe, expect, it, vi } from 'vitest';
import type { Conversation, MessageOut } from '$lib/types';
import Composer from './Composer.svelte';
import {
  ATTEMPT_NOTES,
  attemptNote,
  attemptSavedMessage,
  attemptShortcutLabel,
  composerAction,
  messageNote,
  storedAttempt
} from './attempt';

type Mods = Partial<Record<'shiftKey' | 'ctrlKey' | 'metaKey' | 'altKey' | 'isComposing', boolean> & { keyCode: number }>;
const key = (k: string, mods: Mods = {}) => ({
  key: k,
  keyCode: k === 'Enter' ? 13 : 65,
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

  it("ignores Safari's confirming Enter after IME composition (keyCode 229)", () => {
    // Safari ends the composition before this keydown, so isComposing is already false.
    expect(composerAction(key('Enter', { keyCode: 229 }))).toBeNull();
    expect(composerAction(key('Enter', { keyCode: 229, ctrlKey: true }))).toBeNull();
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
    for (const note of [...Object.values(ATTEMPT_NOTES), attemptSavedMessage('503 Service Unavailable')]) {
      expect(note).not.toMatch(/[—–!]/);
    }
  });

  it("reads a reloaded message's verdict when the send's outcome is not on it", () => {
    const rejected: MessageOut = { role: 'user', content: 'is it 42?', is_attempt: true, attempt_accepted: false };
    expect(messageNote(rejected)).toBe(ATTEMPT_NOTES.rejected);
    expect(messageNote({ ...rejected, attempt_accepted: true })).toBeNull();
    expect(messageNote({ ...rejected, attempt_accepted: null })).toBeNull();
    // The send's own outcome wins (it can say "unverified", which a reload can't).
    expect(messageNote({ ...rejected, attempt_accepted: null, attempt_outcome: 'unverified' })).toBe(ATTEMPT_NOTES.unverified);
    expect(messageNote({ role: 'tutor', content: 'hi' })).toBeNull();
  });
});

describe('after a Submit attempt send fails', () => {
  const convo = (messages: MessageOut[], attempt_logged = false): Conversation => ({
    id: 7,
    concept_id: 1,
    attempt_logged,
    assistance_level: 'medium',
    challenge_level: 'high',
    messages
  });
  const attempt: MessageOut = { role: 'user', content: 'divide by sqrt(d_k)', is_attempt: true, attempt_accepted: true };

  it('finds the attempt the server stored when only the reply failed', async () => {
    const read = vi.fn().mockResolvedValue(convo([{ role: 'user', content: 'hi' }, { role: 'tutor', content: 'yes?' }, attempt], true));
    const stored = await storedAttempt(read, 'divide by sqrt(d_k)');
    expect(read).toHaveBeenCalledOnce();
    expect(stored?.message).toEqual(attempt);
    expect(stored?.conversation.attempt_logged).toBe(true);
  });

  it('says nothing was stored when the attempt never reached the server', async () => {
    const before = convo([{ role: 'user', content: 'hi' }, { role: 'tutor', content: 'yes?' }]);
    expect(await storedAttempt(vi.fn().mockResolvedValue(before), 'divide by sqrt(d_k)')).toBeNull();
    // A tutor reply after it means it is an older, answered message, not this send.
    const answered = convo([attempt, { role: 'tutor', content: 'good' }]);
    expect(await storedAttempt(vi.fn().mockResolvedValue(answered), 'divide by sqrt(d_k)')).toBeNull();
    // An ordinary message with the same text is not the attempt.
    const plain = convo([{ role: 'user', content: 'divide by sqrt(d_k)' }]);
    expect(await storedAttempt(vi.fn().mockResolvedValue(plain), 'divide by sqrt(d_k)')).toBeNull();
    // The re-read failing too: fall back to "nothing was sent".
    expect(await storedAttempt(vi.fn().mockRejectedValue(new Error('down')), 'divide by sqrt(d_k)')).toBeNull();
  });

  it('says plainly that the attempt was saved and the reply failed', () => {
    const text = attemptSavedMessage('529 Overloaded');
    expect(text).toMatch(/^Your attempt was saved, but the tutor's reply failed/);
    expect(text).toContain('529 Overloaded');
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
