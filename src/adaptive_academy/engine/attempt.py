"""The Attempt button: the learner, not the tutor, says "this is my attempt".

The app's central rule (no full answer until you've tried) rests on something the learner
does on purpose. A message sent with Submit attempt (POST .../messages with `attempt: true`)
is checked here, in code, BEFORE the tutor runs, on both tutor paths (engine/tutor.py and
engine/tutor_sdk.py):

- In a conversation that already has an attempt logged there is nothing to unlock: no check,
  no model call, no row. The tutor is told the learner submitted an attempt.
- Otherwise the solution guard's attempt check (`SolutionGuard.confirm_attempt`, one
  copy-role call) reads the learner's own message. A real attempt (reasoning, a step, code,
  right or wrong) writes an accepted `Attempt` row and sets Conversation.attempt_logged,
  which opens the reveal gate (engine/tools.py `reveal_gate`). A bare guess, a request, or a
  question writes a rejected row (the learner's history stays honest) and leaves the gate
  shut. If the check can't run, nothing is recorded and the gate stays shut (fail closed).

Every outcome is traced with a fixed-label event (attempt:submitted, then attempt:accepted,
attempt:rejected or attempt:unverified) whose detail is fixed text, never the learner's
words or the model's reason. The tutor is told what happened in a fixed system note for this
turn only (prompts.TUTOR_ATTEMPT_*), so it can respond to it. The tutor itself has no way to
log an attempt.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlmodel import Session

from adaptive_academy.engine.solution_guard import SolutionGuard
from adaptive_academy.models import Attempt, Conversation, Message
from adaptive_academy.prompts import (
    TUTOR_ATTEMPT_ACCEPTED,
    TUTOR_ATTEMPT_ALREADY_LOGGED,
    TUTOR_ATTEMPT_REJECTED,
    TUTOR_ATTEMPT_UNVERIFIED,
    Prompt,
)

# Outcomes, returned by the message route as `attempt_outcome`.
ACCEPTED = "accepted"
REJECTED = "rejected"
UNVERIFIED = "unverified"
ALREADY_LOGGED = "already_logged"

_NOTES: dict[str, Prompt] = {
    ACCEPTED: TUTOR_ATTEMPT_ACCEPTED,
    REJECTED: TUTOR_ATTEMPT_REJECTED,
    UNVERIFIED: TUTOR_ATTEMPT_UNVERIFIED,
    ALREADY_LOGGED: TUTOR_ATTEMPT_ALREADY_LOGGED,
}

# Event details are shown to the learner ("What the agent did"), so they are fixed strings.
SUBMITTED_DETAIL = "the learner submitted this message as an attempt"
OUTCOME_DETAILS = {
    ACCEPTED: "recorded: the worked solution can now be revealed",
    REJECTED: "not recorded: no reasoning, step, or working in the message",
    UNVERIFIED: "not recorded: the attempt check was unavailable",
}


@dataclass(frozen=True)
class AttemptOutcome:
    status: str  # ACCEPTED | REJECTED | UNVERIFIED | ALREADY_LOGGED
    note: Prompt  # the fixed system note the tutor gets for this turn


def submit_attempt(session: Session, convo: Conversation, message: Message,
                   guard: SolutionGuard, emit: Callable[..., None]) -> AttemptOutcome:
    """Check and record the learner's submitted attempt, before the tutor runs.

    `message` is the learner's stored message (already flushed, marked is_attempt). Releases
    the write lock before the check (F5: it may make a model call) and commits what it
    writes. Never raises on a check failure: that is the UNVERIFIED outcome."""
    emit("attempt:submitted", SUBMITTED_DETAIL)
    if convo.attempt_logged:
        status = ALREADY_LOGGED
    else:
        session.commit()
        if guard.confirm_attempt():
            status = ACCEPTED
        elif guard.attempt_check_failed:
            status = UNVERIFIED
        else:
            status = REJECTED
        if status != UNVERIFIED:
            session.add(Attempt(conversation_id=convo.id, concept_id=convo.concept_id,
                                message_id=message.id, accepted=status == ACCEPTED))
        if status == ACCEPTED:
            convo.attempt_logged = True
            session.add(convo)
        emit(f"attempt:{status}", OUTCOME_DETAILS[status])
    note = _NOTES[status]
    emit("prompt", note.tag)
    session.commit()
    return AttemptOutcome(status, note)


def with_attempt_note(system: str, outcome: AttemptOutcome | None) -> str:
    """The turn's system prompt, with the attempt note last when the learner submitted one."""
    return system if outcome is None else f"{system}\n\n{outcome.note}"
