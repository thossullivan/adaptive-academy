from dataclasses import dataclass

from sqlmodel import Session

from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.prompts import build_tutor_system_prompt
from adaptive_academy.engine.tools import TIERS, TOOLS
from adaptive_academy.llm.types import LLMClient, LLMResponse, ToolCall
from adaptive_academy.models import AgentEvent, Concept, Conversation, Message

_MAX_STEPS = 6


@dataclass
class TurnResult:
    reply: str
    events: list[AgentEvent]


def _history(convo: Conversation) -> list[dict]:
    role_map = {"user": "user", "tutor": "assistant"}
    return [{"role": role_map[m.role], "content": m.content} for m in convo.messages]


def run_tutor_turn(
    session: Session,
    convo: Conversation,
    user_text: str,
    llm: LLMClient,
) -> TurnResult:
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(conversation_id=convo.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    # Persist the incoming user message.
    session.add(Message(conversation_id=convo.id, role="user", content=user_text))
    session.commit()
    session.refresh(convo)

    concept = session.get(Concept, convo.concept_id)
    levels = compute_levels(concept.estimate if concept else None)
    emit("levels", f"assistance={levels.assistance} challenge={levels.challenge}")
    system = build_tutor_system_prompt(concept.name if concept else "", levels)

    messages = _history(convo)
    reply_text = ""

    for _ in range(_MAX_STEPS):
        emit("llm_call")
        resp: LLMResponse = llm.complete(system=system, messages=messages, tools=TOOLS)

        if not resp.tool_calls:
            reply_text = resp.text
            break

        # Echo the assistant tool-use turn into the running transcript.
        messages.append({"role": "assistant", "content": _assistant_tool_blocks(resp)})
        tool_results = []
        for call in resp.tool_calls:
            ok, payload = _execute_tool(session, convo, call, emit)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": payload}
            )
            if call.name == "reveal_solution" and ok:
                reply_text = call.input.get("text", "")
        messages.append({"role": "user", "content": tool_results})

    # Persist the tutor reply.
    session.add(Message(conversation_id=convo.id, role="tutor", content=reply_text))
    session.commit()
    return TurnResult(reply=reply_text, events=events)


def _assistant_tool_blocks(resp: LLMResponse) -> list[dict]:
    blocks: list[dict] = []
    if resp.text:
        blocks.append({"type": "text", "text": resp.text})
    for call in resp.tool_calls:
        blocks.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
        )
    return blocks


def _execute_tool(session, convo: Conversation, call: ToolCall, emit) -> tuple[bool, str]:
    tier = TIERS.get(call.name, "auto")

    if call.name == "log_attempt":
        convo.attempt_logged = True
        session.add(convo)
        session.commit()
        emit("tool:log_attempt", call.input.get("summary", ""))
        return True, "ok: attempt recorded"

    if call.name == "reveal_solution":
        if tier == "gated" and not convo.attempt_logged:
            emit("tool:reveal_solution:blocked")
            return False, (
                "BLOCKED: the learner has not logged an attempt yet. Do NOT reveal the "
                "solution. Give a single hint or Socratic question instead."
            )
        emit("tool:reveal_solution:allowed")
        return True, "ok: solution permitted"

    emit(f"tool:{call.name}:unknown")
    return False, f"unknown tool {call.name}"
