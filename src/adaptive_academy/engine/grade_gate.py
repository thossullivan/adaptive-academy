"""Run a grader call through its named output checks — the I/O half of output_checks.

`checked_completion` makes the grader call, checks the answer (output_checks.check_output),
and acts on output_checks.decide():

  accept      return the parsed answer (WARN results are recorded, never blocking);
  regenerate  append the grader's own answer and a GRADE_CORRECTION turn naming the failed
              rule ids, and call again — append-only, the original turns are never edited;
  reject      record `grade:rejected`, commit the trace, raise GradeCheckError
              (llm/errors.py → `invalid_output`, HTTP 502).

Every check is recorded as an AgentEvent (`grade:check`, `grade:regenerated`,
`grade:rejected`) through the caller's `emit`, so the trace shows what the gate did.

Fail closed: callers run this BEFORE they write any Assessment row, estimate or outcome, so a
rejected grade leaves the learning record untouched. On rejection the session is committed so
the trace events survive the error; callers must have nothing but trace events pending then.
"""

from collections.abc import Callable
from typing import Any

from sqlmodel import Session

from adaptive_academy.engine.output_checks import (
    ACCEPT,
    REJECT,
    CheckContext,
    CheckReport,
    GradeCheckError,
    Rubric,
    check_output,
    correction_message,
    decide,
    summarize,
)
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.prompts import GRADE_CORRECTION

Emit = Callable[[str, str], None]

# An assistant turn must have content; an empty reply is echoed back as this placeholder.
_EMPTY_REPLY = "(empty reply)"


def checked_completion(
    session: Session,
    llm: LLMClient,
    *,
    system: str,
    user: str,
    rubric: Rubric,
    emit: Emit,
    ctx: CheckContext | None = None,
) -> tuple[dict[str, Any], CheckReport]:
    """One grader call, checked; at most one regeneration. Returns (answer, final report)."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    attempt = 1
    while True:
        resp = llm.complete(system=system, messages=messages, tools=[])
        data, report = check_output(rubric, resp.text, ctx)
        emit("grade:check", summarize(report, attempt))
        action = decide(report, attempt)
        if action == ACCEPT:
            assert data is not None  # a passing report always parsed (J1)
            return data, report
        if action == REJECT:
            emit("grade:rejected",
                 f"{rubric.name} rejected after {attempt} attempts: "
                 f"FAIL {','.join(report.failed_ids)}; nothing recorded")
            session.commit()  # keep the trace; no learning state is pending (see docstring)
            raise GradeCheckError(rubric.name, report.failed_ids)
        emit("grade:regenerated", f"{rubric.name} after FAIL {','.join(report.failed_ids)}")
        emit("prompt", GRADE_CORRECTION.tag)
        messages = [
            *messages,
            {"role": "assistant", "content": resp.text if resp.text.strip() else _EMPTY_REPLY},
            {"role": "user", "content": correction_message(report)},
        ]
        attempt += 1
