"""The generation-first Tutor turn, run on the Claude subscription via the Agent SDK.

Selected in agent_sdk mode (see api/routes_conversations.py). The whole turn is ONE SDK
`query()` with two in-process tools — `log_attempt` and `reveal_solution` — where the
attempt-gate is **code-enforced inside the reveal_solution handler** (the SDK's `can_use_tool`
callback needs streaming-input mode; the in-handler gate is simpler and keeps the guardrail in
code). The gate decision is the shared `reveal_gate` used by the raw-API tutor too.

The Agent SDK runs the agent loop and executes the tools; we collect the final
`ResultMessage.result` as the tutor's reply. Conversation history is flattened into the prompt
(the SDK query is stateless), mirroring how the API path re-sends the full message list.
"""

import asyncio

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    create_sdk_mcp_server,
    query,
    tool,
)
from sqlmodel import Session

from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.memory import index_message, memory_blocks_for_tutor
from adaptive_academy.engine.tools import reveal_gate
from adaptive_academy.engine.tutor import TurnResult, _FALLBACK
from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.retriever_types import Hit, Retriever
from adaptive_academy.llm.types import AgentSDKError
from adaptive_academy.models import AgentEvent, Concept, Conversation, Message
from adaptive_academy.prompts import build_tutor_system_prompt

_MAX_TURNS = 6


def format_history(convo: Conversation) -> str:
    """Flatten the conversation into a single prompt (the SDK query is stateless)."""
    lines = [f"{'Learner' if m.role == 'user' else 'Tutor'}: {m.content}"
             for m in convo.messages]
    return "\n".join(lines)


def _text_result(text: str, *, is_error: bool = False) -> dict:
    out = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


def log_attempt_result(convo: Conversation, emit, args: dict) -> dict:
    """Tool body for log_attempt — records the learner's attempt. Extracted so the
    attempt-gate can be unit-tested without the live SDK."""
    convo.attempt_logged = True
    emit("tool:log_attempt", str(args.get("summary", "")))
    return _text_result("ok: attempt recorded")


def reveal_solution_result(convo: Conversation, emit, args: dict) -> dict:
    """Tool body for reveal_solution — the code-enforced attempt-gate. When blocked it
    returns the BLOCKED message (is_error) and NEVER the solution text."""
    allowed, msg = reveal_gate(convo.attempt_logged)
    emit(f"tool:reveal_solution:{'allowed' if allowed else 'blocked'}")
    if not allowed:
        return _text_result(msg, is_error=True)
    return _text_result(str(args.get("text", "")))


def run_tutor_turn_sdk(
    session: Session,
    convo: Conversation,
    user_text: str,
    *,
    role: str = "reasoning",
    retriever: Retriever | None = None,
) -> TurnResult:
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(conversation_id=convo.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    user_message = Message(conversation_id=convo.id, role="user", content=user_text)
    session.add(user_message)
    session.flush()
    index_message(
        session,
        user_message,
        concept_id=convo.concept_id,
        topic_id=convo.topic_id,
    )
    session.commit()
    session.refresh(convo)

    concept = session.get(Concept, convo.concept_id)
    levels = compute_levels(concept.estimate if concept else None)
    emit("levels", f"assistance={levels.assistance} challenge={levels.challenge}")
    memory_block = ""
    covered_block = ""
    memory_hits: list[Hit] = []
    if retriever is not None and concept is not None:
        memory_block, covered_block, memory_hits = memory_blocks_for_tutor(
            session,
            retriever,
            convo,
            concept,
            user_text,
        )
    system = build_tutor_system_prompt(
        concept.name if concept else "",
        levels,
        memory_block=memory_block,
        covered_block=covered_block,
    )
    prompt = format_history(convo)

    @tool("log_attempt", "Record that the learner made a genuine attempt", {"summary": str})
    async def _log_attempt(args):  # noqa: ANN001
        return log_attempt_result(convo, emit, args)

    @tool("reveal_solution", "Reveal the full worked solution (only after an attempt)",
          {"text": str})
    async def _reveal_solution(args):  # noqa: ANN001
        return reveal_solution_result(convo, emit, args)

    server = create_sdk_mcp_server("tutor", tools=[_log_attempt, _reveal_solution])

    async def _run() -> str:
        text = ""
        async for msg in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                model=get_model(role), system_prompt=system,
                mcp_servers={"tutor": server},
                allowed_tools=["mcp__tutor__log_attempt", "mcp__tutor__reveal_solution"],
                permission_mode="bypassPermissions", max_turns=_MAX_TURNS,
                setting_sources=[]),
        ):
            if isinstance(msg, ResultMessage):
                if getattr(msg, "is_error", False):
                    raise AgentSDKError(getattr(msg, "result", "") or "agent SDK tutor error")
                text = getattr(msg, "result", "") or ""
        return text

    emit("tutor:sdk", "subscription tutor turn")
    reply = asyncio.run(_run())
    if not reply:
        emit("max_steps_exhausted")
        reply = _FALLBACK

    tutor_message = Message(conversation_id=convo.id, role="tutor", content=reply)
    session.add(tutor_message)
    session.flush()
    index_message(
        session,
        tutor_message,
        concept_id=convo.concept_id,
        topic_id=convo.topic_id,
        levels=levels,
    )
    session.commit()
    return TurnResult(reply=reply, events=events, memory=memory_hits)
