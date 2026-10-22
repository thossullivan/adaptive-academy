"""The generation-first Tutor turn, run on the Claude subscription via the Agent SDK.

Selected in agent_sdk mode (see api/routes_conversations.py). The whole turn is ONE SDK
`query()` with one in-process tool, `reveal_solution`, where the attempt-gate is
**code-enforced inside its handler** (the SDK's `can_use_tool` callback needs streaming-input
mode; the in-handler gate is simpler and keeps the guardrail in code). The gate decision is
the shared `reveal_gate` used by the raw-API tutor too. Only the learner opens the gate, with
Submit attempt, checked before the query runs (engine/attempt.py), as on the API path.

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

from adaptive_academy.engine.attempt import AttemptOutcome, submit_attempt, with_attempt_state
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
    attempt: bool = False,
) -> TurnResult:
    """One learner turn on the subscription. `attempt` is the Submit attempt button, checked
    and recorded before the query runs (engine/attempt.py). `guard_llm` is the solution
    guard's copy-role client (api/deps.get_guard_llm); None runs the guard's deterministic
    screen only, and then no attempt is ever recorded (the check fails closed)."""
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(conversation_id=convo.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    user_message = Message(conversation_id=convo.id, role="user", content=user_text,
                           is_attempt=True if attempt else None)
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
    prompt = format_history(convo)
    # The guard also sees the tutor's last stored message (often the question answered).
    previous_tutor = next((m.content for m in reversed(convo.messages) if m.role == "tutor"), "")
    guard = SolutionGuard(concept=concept_name, learner_text=user_text, llm=guard_llm,
                          emit=emit, previous_tutor=previous_tutor)
    # Checked here, before (and outside) the SDK's event loop: the subscription guard client
    # runs its own asyncio.run.
    outcome: AttemptOutcome | None = None
    if attempt:
        outcome = submit_attempt(session, convo, user_message, guard, emit)
    system = with_attempt_state(build_tutor_system_prompt(
        concept_name,
        levels,
        memory_block=memory_block,
        covered_block=covered_block,
    ), outcome, attempt_logged=convo.attempt_logged)

    # The text of an allowed reveal. As on the API path, an allowed reveal is the reply: the
    # tool result only goes back to the model, which may then just say "see above", and the
    # learner would never see the solution.
    revealed: list[str] = []

    @tool("reveal_solution", "Reveal the full worked solution (only after an attempt)",
          {"text": str})
    async def _reveal_solution(args):  # noqa: ANN001
        result = reveal_solution_result(convo, emit, args)
        if not result.get("is_error") and str(args.get("text", "")).strip():
            revealed.append(str(args["text"]))
        return result

    server = create_sdk_mcp_server("tutor", tools=[_reveal_solution])

    model = get_model(role)

    async def _run(prompt: str) -> str:
        text = ""
        async for msg in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                model=model, system_prompt=with_today(system),
                mcp_servers={"tutor": server},
                # tools=[] turns off ALL of Claude Code's built-in tools (Bash, Read,
                # Write, Edit, WebFetch, ...). Without it the CLI gets its default set,
                # and with bypassPermissions the tutor could run them: rewrite the
                # database to open the reveal gate, or act on instructions planted in an
                # ingested vault note or web source. allowed_tools only auto-approves; it
                # does not restrict. The in-process MCP tool is unaffected.
                tools=[],
                allowed_tools=["mcp__tutor__reveal_solution"],
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
    # refresh reloads convo so the in-process tool only reads it and adds event rows (no
    # query, so no autoflush) until the reply is persisted below.
    session.commit()
    session.refresh(convo)
    reply = asyncio.run(_run(prompt))
    if revealed:
        reply = revealed[-1]  # the tool is the authoritative source of the answer
    elif not reply:
        emit("max_steps_exhausted")
        reply = _FALLBACK
    elif not convo.attempt_logged:
        reply = _guarded_reply(session, convo, guard, reply, prompt, _run)

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
    return TurnResult(reply=reply, events=events, memory=memory_hits,
                      attempt_outcome=outcome.status if outcome else None)


def _guarded_reply(session: Session, convo: Conversation, guard: SolutionGuard, draft: str,
                   prompt: str, run) -> str:  # noqa: ANN001
    """The solution guard on a pre-attempt subscription reply (engine/solution_guard.py).

    A withheld draft gets ONE regeneration: a second query whose prompt is the same flattened
    history with the draft and the correction appended (append-only, like the API path).
    Nothing in that run can log an attempt (only Submit attempt can, before the turn), so
    reveal_solution stays gated and its reply is always checked; a second leak stores
    GUARD_FALLBACK. Only the returned text is ever stored.
    """
    # Release the write lock before the check (F5): it may make a model call, and the
    # in-process tool may have left events pending.
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
