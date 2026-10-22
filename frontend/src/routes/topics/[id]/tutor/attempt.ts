import type { AttemptOutcome } from '$lib/types';

/** The keys the composer reads off a keydown (a KeyboardEvent has all of them). */
export interface ComposerKey {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  isComposing: boolean;
}

/**
 * What a keydown in the composer does: Enter sends, Ctrl+Enter (Cmd+Enter on a Mac) submits
 * the message as an attempt, and anything else (Shift+Enter for a new line, an IME still
 * composing) is left to the textarea.
 */
export function composerAction(e: ComposerKey): 'send' | 'attempt' | null {
  if (e.key !== 'Enter' || e.isComposing) return null;
  if (e.ctrlKey || e.metaKey) return 'attempt';
  if (e.shiftKey || e.altKey) return null;
  return 'send';
}

/** The attempt shortcut as the learner's keyboard names it. */
export function attemptShortcutLabel(isMac: boolean): string {
  return isMac ? '⌘ Enter' : 'Ctrl+Enter';
}

/** Shown under a submitted attempt that was not logged (POST .../messages attempt_outcome). */
export const ATTEMPT_NOTES: Partial<Record<AttemptOutcome, string>> = {
  rejected: 'Not logged as an attempt yet. Add your reasoning or a first step, then submit again.',
  unverified: "Your attempt couldn't be checked just now, so it wasn't logged. Try submitting it again in a moment."
};

export function attemptNote(outcome: AttemptOutcome | null | undefined): string | null {
  return (outcome && ATTEMPT_NOTES[outcome]) || null;
}
