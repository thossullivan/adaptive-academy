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
from adaptive_academy.engine.solution_guard import (
    GUARD_FALLBACK,
    PASS,
    REGENERATE,
    SolutionGuard,
)
from adaptive_academy.engine.tools import reveal_gate
from adaptive_academy.engine.tutor import TurnResult, _FALLBACK
from adaptive_academy.llm.agent_sdk_client import record_sdk_result
from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.retriever_types import Hit, Retriever
from adaptive_academy.llm.today import with_today
from adaptive_academy.llm.types import AgentSDKError, LLMClient
from adaptive_academy.models import AgentEvent, Concept, Conversation, Message
from adaptive_academy.prompts import TUTOR_GUARD_CORRECTION, build_tutor_system_prompt

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


def log_attempt_result(convo: Conversation, emit, args: dict, *,
                       guard: SolutionGuard | None = None) -> dict:
    """Tool body for log_attempt — records the learner's attempt. Extracted so the
    attempt-gate can be unit-tested without the live SDK. While the solution guard is
    regenerating a withheld draft the attempt is deferred, not recorded: the tutor can't
    unlock the gate mid-turn (run_tutor_turn_sdk records it after the turn if the reply
    passed review)."""
    if guard is not None and guard.regenerating:
        return _text_result(guard.defer_attempt(str(args.get("summary", ""))))
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
    guard_llm: LLMClient | None = None,
) -> TurnResult:
    """One learner turn on the subscription. `guard_llm` is the solution guard's copy-role
    client (api/deps.get_guard_llm); None runs the guard's deterministic screen only."""
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
        retriever=retriever,
    )
    session.commit()
    session.refresh(convo)

    concept = session.get(Concept, convo.concept_id)
    concept_name = concept.name if concept else ""
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
        concept_name,
        levels,
        memory_block=memory_block,
        covered_block=covered_block,
    )
    prompt = format_history(convo)
    # Built before the run so the log_attempt tool can see whether a regeneration is under
    # way. The guard also sees the tutor's last stored message (often the question answered).
    previous_tutor = next((m.content for m in reversed(convo.messages) if m.role == "tutor"), "")
    guard = SolutionGuard(concept=concept_name, learner_text=user_text, llm=guard_llm,
                          emit=emit, previous_tutor=previous_tutor)

    @tool("log_attempt", "Record that the learner made a genuine attempt", {"summary": str})
    async def _log_attempt(args):  # noqa: ANN001
        return log_attempt_result(convo, emit, args, guard=guard)

    @tool("reveal_solution", "Reveal the full worked solution (only after an attempt)",
          {"text": str})
    async def _reveal_solution(args):  # noqa: ANN001
        return reveal_solution_result(convo, emit, args)

    server = create_sdk_mcp_server("tutor", tools=[_log_attempt, _reveal_solution])

    model = get_model(role)

    async def _run(prompt: str) -> str:
        text = ""
        async for msg in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                model=model, system_prompt=with_today(system),
                mcp_servers={"tutor": server},
                allowed_tools=["mcp__tutor__log_attempt", "mcp__tutor__reveal_solution"],
                permission_mode="bypassPermissions", max_turns=_MAX_TURNS,
                setting_sources=[]),
        ):
            if isinstance(msg, ResultMessage):
                record_sdk_result(msg, model=model, role=role, operation="tutor_sdk")
                if getattr(msg, "is_error", False):
                    raise AgentSDKError(getattr(msg, "result", "") or "agent SDK tutor error")
                text = getattr(msg, "result", "") or ""
        return text

    emit("tutor:sdk", "subscription tutor turn")
    # Release the write lock before the SDK run (F5): pending events, flushed by the lazy
    # load in format_history, would otherwise hold it for the whole multi-turn query. The
    # refresh reloads convo so the in-process tools only set attributes / add rows (no
    # query, so no autoflush) until the reply is persisted below.
    session.commit()
    session.refresh(convo)
    reply = asyncio.run(_run(prompt))
    if not reply:
        emit("max_steps_exhausted")
        reply = _FALLBACK
    elif not convo.attempt_logged:
        reply = _guarded_reply(session, convo, guard, reply, prompt, _run)
        # An attempt the regeneration logged counts only now, and only if its reply passed
        # review: never mid-turn, and never for a turn that ended in the guard's fallback.
        if guard.take_deferred_attempt():
            convo.attempt_logged = True
            session.add(convo)

    tutor_message = Message(conversation_id=convo.id, role="tutor", content=reply)
    session.add(tutor_message)
    session.flush()
    index_message(
        session,
        tutor_message,
        concept_id=convo.concept_id,
        topic_id=convo.topic_id,
        levels=levels,
        retriever=retriever,
    )
    session.commit()
    return TurnResult(reply=reply, events=events, memory=memory_hits)


def _guarded_reply(session: Session, convo: Conversation, guard: SolutionGuard, draft: str,
                   prompt: str, run) -> str:  # noqa: ANN001
    """The solution guard on a pre-attempt subscription reply (engine/solution_guard.py).

    A withheld draft gets ONE regeneration: a second query whose prompt is the same flattened
    history with the draft and the correction appended (append-only, like the API path).
    During that run log_attempt is deferred (so reveal_solution stays gated), and its reply
    is always checked; a second leak stores GUARD_FALLBACK. Only the returned text is ever
    stored.
    """
    # Release the write lock before the check (F5): it may make a model call, and the
    # in-process tools may have left events pending.
    session.commit()
    decision = guard.review(draft)
    if decision == PASS:
        return draft
    if decision != REGENERATE:
        return GUARD_FALLBACK
    retry_prompt = f"{prompt}\nTutor: {draft}\n\n{TUTOR_GUARD_CORRECTION}"
    session.commit()
    session.refresh(convo)  # as before the first run: the tools then never query (F5)
    try:
        second = asyncio.run(run(retry_prompt))
    except Exception as exc:
        return guard.regeneration_failed(exc)
    if not second:
        return guard.regeneration_failed("empty reply")
    session.commit()
    return second if guard.review(second) == PASS else GUARD_FALLBACK
