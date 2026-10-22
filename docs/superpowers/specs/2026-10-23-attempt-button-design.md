# Attempt button: design

Status: approved by Tom, 2026-10-23.

## Why

Today the tutor model decides when the learner has made an attempt, by calling its
`log_attempt` tool. A model check now confirms the learner's message really is an attempt, but
it is still the model's call about the learner's own message. The app's central rule ("no full
answer until you've tried") should rest on something the learner does on purpose.

## What changes

1. **The composer has two actions.** "Send" asks or talks, as today. "Submit attempt" sends the
   message as the learner's attempt. Keyboard: the existing send shortcut stays on Send; a
   separate, documented shortcut submits an attempt. Both are reachable by keyboard and screen
   reader, and the header keeps showing **no attempt yet** / **attempt logged**.
2. **The code records the attempt, not the tutor.** `POST /api/conversations/{id}/messages`
   takes `attempt: bool` (default false). When it is true, before the tutor runs:
   - the existing substance check (the solution guard's `learner_attempted` judgement) reads the
     message. A real attempt (reasoning, a step, code, right or wrong) is recorded. A bare guess,
     a request, or a question is not.
   - an accepted attempt writes an `Attempt` row (conversation, concept, the message, the time)
     and sets `Conversation.attempt_logged`. A rejected one writes the row with
     `accepted = false` so the learner's history is honest, and leaves the gate shut.
   - fixed-label events: `attempt:submitted`, `attempt:accepted`, `attempt:rejected`,
     `attempt:unverified` (check unavailable: not recorded, gate stays shut, as today).
   - the tutor is told, in a fixed system note for that turn, whether the attempt was recorded
     or why not, so it can respond to it.
3. **The tutor loses `log_attempt`.** It can no longer open the gate. Its prompt tells it to
   suggest the button when the learner seems to be attempting in an ordinary message ("If that's
   your attempt, submit it with Submit attempt"). `reveal_solution` and its gate are unchanged.
4. **Both tutor paths** (API key and Claude subscription) behave the same.
5. **The UI tells the learner what happened.** Accepted: the header turns to attempt logged. Not
   accepted: a short, kind inline note under the message ("Add your reasoning or a first step,
   then submit again"), plus the tutor's reply.

## Data

- New table `attempt`: id, conversation_id (FK), concept_id (FK), message_id (FK), accepted
  (bool), created_at. Plain `op.add_column`-style migration (a new table), populated-DB test.
- `Message.is_attempt` (nullable bool) so the transcript can mark attempt messages.
- The demo's stored conversations mark their attempt message and get matching `Attempt` rows.
- Export (JSON) and backup include the new table automatically; verify.

## Not changing

The solution guard on replies before an attempt, the regeneration, the fallback, and the reveal
gate. The eval and grading are untouched.

## Tests

Engine and route tests on both paths: accepted, rejected (bare guess, request), unverified,
already unlocked (no check, no new row), the tutor no longer has `log_attempt`, the reveal stays
blocked until an accepted attempt. Frontend unit tests for the composer; e2e for both buttons,
the header change, the rejected note, keyboard use, and axe with zero violations.
