import type { AttemptOutcome, Conversation, MessageOut } from '$lib/types';

/** The keys the composer reads off a keydown (a KeyboardEvent has all of them). */
export interface ComposerKey {
  key: string;
  /** 229 while an IME owns the key (Safari's confirming Enter, after isComposing has ended). */
  keyCode: number;
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
  if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return null;
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

/**
 * The note under a message: the send's own outcome when the page has it, else the stored
 * verdict (GET /api/conversations/{id} `attempt_accepted`), so a re-read transcript still
 * marks an attempt that was not logged.
 */
export function messageNote(m: MessageOut): string | null {
  return attemptNote(m.attempt_outcome ?? (m.is_attempt && m.attempt_accepted === false ? 'rejected' : null));
}

/**
 * After a Submit attempt send fails: did the attempt reach the server anyway? The attempt is
 * checked and stored before the tutor runs, so a failed tutor call (an overload, say) can
 * leave it saved, and logged. Re-read the conversation: the attempt was stored when the
 * transcript ends with it (no reply after it). Null when it wasn't, or the re-read fails.
 */
export async function storedAttempt(
  read: () => Promise<Conversation>,
  content: string
): Promise<{ conversation: Conversation; message: MessageOut } | null> {
  const conversation = await read().catch(() => null);
  const last = conversation?.messages.at(-1);
  if (!conversation || !last || last.role !== 'user' || !last.is_attempt || last.content !== content) return null;
  return { conversation, message: last };
}

export function attemptSavedMessage(error: string): string {
  return `Your attempt was saved, but the tutor's reply failed (${error}). Send a message when you're ready to carry on.`;
}
