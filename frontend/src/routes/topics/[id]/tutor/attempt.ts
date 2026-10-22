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
 * leave it saved. Re-read the conversation: the attempt was stored when the transcript has
 * exactly one more message than before the send (`priorCount`) and ends with it, with no
 * reply after it. The count stops an identical earlier attempt from matching. Null when it
 * wasn't stored, or the re-read fails.
 */
export async function storedAttempt(
  read: () => Promise<Conversation>,
  content: string,
  priorCount: number
): Promise<{ conversation: Conversation; message: MessageOut } | null> {
  const conversation = await read().catch(() => null);
  const last = conversation?.messages.at(-1);
  if (!conversation || conversation.messages.length !== priorCount + 1) return null;
  if (!last || last.role !== 'user' || !last.is_attempt || last.content !== content) return null;
  // What the check decided: logged, not logged, or not checked (no Attempt row written).
  const outcome: AttemptOutcome =
    last.attempt_accepted === true || conversation.attempt_logged
      ? 'accepted'
      : last.attempt_accepted === false
        ? 'rejected'
        : 'unverified';
  return { conversation, message: { ...last, attempt_outcome: outcome } };
}

/** The toast after a failed reply to a stored attempt, worded for what happened to it. */
export function attemptSavedMessage(error: string, outcome: AttemptOutcome | null = 'accepted'): string {
  if (outcome === 'rejected') {
    return `Your attempt was saved but not logged: add your reasoning or a first step and submit again. The tutor's reply also failed (${error}).`;
  }
  if (outcome === 'unverified') {
    return `Your attempt was saved but couldn't be checked, so it isn't logged yet. Submit it again in a moment. The tutor's reply failed (${error}).`;
  }
  return `Your attempt was saved and logged, but the tutor's reply failed (${error}). Send a message when you're ready to carry on.`;
}
