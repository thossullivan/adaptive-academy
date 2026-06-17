"""Prompt traceability — stamp which prompt@version produced each LLM call.

Engines that already keep an `emit(kind, detail)` closure should call
`emit("prompt", PROMPT.tag)`. Engines without one use `trace_prompt(...)`, which writes the
same `AgentEvent` directly. Either way the tag lands in SQLite (kind="prompt") and surfaces
in the in-app activity feeds — our lightweight stand-in for a prompt-management service.
"""

from sqlmodel import Session

from adaptive_academy.models import AgentEvent
from adaptive_academy.prompts import Prompt


def trace_prompt(
    session: Session,
    prompt: Prompt,
    *,
    topic_id: int | None = None,
    conversation_id: int | None = None,
) -> AgentEvent:
    ev = AgentEvent(
        topic_id=topic_id,
        conversation_id=conversation_id,
        kind="prompt",
        detail=prompt.tag,
    )
    session.add(ev)
    return ev
