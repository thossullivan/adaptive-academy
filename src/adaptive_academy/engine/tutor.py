from collections.abc import Callable
from dataclasses import dataclass, field

from sqlmodel import Session

from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.memory import index_message, memory_blocks_for_tutor
from adaptive_academy.engine.solution_guard import (
    FALLBACK,
    GUARD_FALLBACK,
    REGENERATE,
    SolutionGuard,
)
from adaptive_academy.engine.tools import TIERS, TOOLS, reveal_gate
from adaptive_academy.llm.retriever_types import Hit, Retriever
from adaptive_academy.llm.types import LLMClient, LLMResponse, ToolCall
from adaptive_academy.models import AgentEvent, Concept, Conversation, Message
from adaptive_academy.prompts import TUTOR_GUARD_CORRECTION, build_tutor_system_prompt

_MAX_STEPS = 6
# Steps a regeneration is always left, however late the withheld draft came: two tool steps
# and the reply.
_REGEN_STEPS = 3
_FALLBACK = "Let's slow down — tell me what you've tried so far, and we'll work from there."
_REFUSAL = (
    "I can't respond to that one — the model declined it. Try rephrasing, or tell me what "
    "you've tried so far on this concept."
)


@dataclass
class TurnResult:
    reply: str
    events: list[AgentEvent]
    memory: list[Hit] = field(default_factory=list)


def _history(convo: Conversation) -> list[dict]:
    role_map = {"user": "user", "tutor": "assistant"}
    return [{"role": role_map[m.role], "content": m.content} for m in convo.messages]


def run_tutor_turn(
    session: Session,
    convo: Conversation,
    user_text: str,
    llm: LLMClient,
    *,
    retriever: Retriever | None = None,
    guard_llm: LLMClient | None = None,
) -> TurnResult:
    """One learner turn. `guard_llm` is the solution guard's copy-role client
    (api/deps.get_guard_llm); None runs the guard's deterministic screen only."""
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(conversation_id=convo.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    # Persist the incoming user message.
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

    messages = _history(convo)
    reply_text = ""
    # The guard also sees the tutor's last stored message: often the question being answered.
    previous_tutor = next((m["content"] for m in reversed(messages)
                           if m["role"] == "assistant"), "")
    guard = SolutionGuard(concept=concept.name if concept else "", learner_text=user_text,
                          llm=guard_llm, emit=emit, previous_tutor=previous_tutor)

    step = 0
    max_steps = _MAX_STEPS
    while step < max_steps:
        step += 1
        emit("llm_call", f"step={step}")
        # Release the write lock before every model call (F5): pending trace events (and
        # the lazy load in _history) would otherwise hold it for the whole round trip,
        # stalling every other writer, the usage row this call records included.
        session.commit()
        try:
            resp: LLMResponse = llm.complete(system=system, messages=messages, tools=TOOLS)
        except Exception as exc:
            if not guard.regenerating:
                raise
            # The withheld draft is gone either way: store the guard's fallback, not a 5xx.
            reply_text = guard.regeneration_failed(exc)
            break

        if resp.stop_reason == "refusal":
            # A safety decline (Claude 5.5 models): never show or store partial declined
            # text; store a legible, non-empty notice so the history stays resendable.
            emit("llm_refusal")
            reply_text = _REFUSAL
            break

        if not resp.tool_calls:
            reply_text = resp.text
            if not reply_text.strip():
                emit("empty_reply", f"stop_reason={resp.stop_reason}")
            elif guard.regenerating or not convo.attempt_logged:
                # The solution guard: a reply finalised before any attempt is logged (this
                # turn's log_attempt included) must not hand over the answer. A regenerated
                # reply is always reviewed (it was pre-attempt, and log_attempt is refused
                # while regenerating). Release the write lock first (F5): the check may make
                # a model call.
                session.commit()
                decision = guard.review(reply_text)
                if decision == REGENERATE:
                    # Append-only: the withheld draft goes back as the assistant turn, echoed
                    # exactly (thinking blocks included), and the correction as a new user
                    # turn. The draft itself is never stored, indexed, or returned.
                    messages.append({"role": "assistant",
                                     "content": _assistant_tool_blocks(resp)})
                    messages.append({"role": "user", "content": str(TUTOR_GUARD_CORRECTION)})
                    reply_text = ""
                    # A late draft still leaves the regeneration room for a tool step or two
                    # (a refused log_attempt, a blocked reveal) before its reply.
                    max_steps = max(max_steps, step + _REGEN_STEPS)
                    continue
                if decision == FALLBACK:
                    reply_text = GUARD_FALLBACK
            break

        # Echo the assistant tool-use turn into the running transcript.
        messages.append({"role": "assistant", "content": _assistant_tool_blocks(resp)})
        tool_results = []
        revealed_text: str | None = None
        for call in resp.tool_calls:
            ok, payload = _execute_tool(session, convo, call, emit, guard)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": payload}
            )
            if call.name == "reveal_solution" and ok:
                revealed_text = call.input.get("text", "")
        messages.append({"role": "user", "content": tool_results})

        # An allowed reveal is terminal: the tool is the authoritative source of the answer
        # (and is never guarded: the attempt-gate already allowed it).
        if revealed_text is not None:
            reply_text = revealed_text
            break

    if not reply_text.strip():
        # Never store an empty / whitespace-only tutor message: it is resent as an
        # assistant turn next time, and the API rejects empty text content.
        if not any(e.kind == "empty_reply" for e in events):
            emit("max_steps_exhausted")
        reply_text = _FALLBACK

    # Persist the tutor reply.
    tutor_message = Message(conversation_id=convo.id, role="tutor", content=reply_text)
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
    return TurnResult(reply=reply_text, events=events, memory=memory_hits)


def _assistant_tool_blocks(resp: LLMResponse) -> list[dict]:
    # For a tool-use turn, and for a draft the solution guard withheld.
    # Echo the assistant turn exactly as the API returned it when the client exposes it:
    # within a tool-use turn, thinking blocks must go back complete and unmodified (signature
    # and empty text included) or the API rejects the request. Rebuild only for clients
    # without raw blocks (scripted fakes), which never produce thinking blocks.
    if resp.raw_content is not None:
        return list(resp.raw_content)
    blocks: list[dict] = []
    if resp.text:
        blocks.append({"type": "text", "text": resp.text})
    for call in resp.tool_calls:
        blocks.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
        )
    return blocks


def _execute_tool(
    session: Session,
    convo: Conversation,
    call: ToolCall,
    emit: Callable[..., None],
    guard: SolutionGuard | None = None,
) -> tuple[bool, str]:
    tier = TIERS.get(call.name, "auto")

    if call.name == "log_attempt":
        if guard is not None and guard.regenerating:
            # Rewriting a withheld draft: the tutor can't unlock the gate for itself. Nothing
            # is recorded, so reveal_solution stays gated and the reply is still reviewed.
            return False, guard.refuse_attempt()
        convo.attempt_logged = True
        session.add(convo)
        session.commit()
        emit("tool:log_attempt", call.input.get("summary", ""))
        return True, "ok: attempt recorded"

    if call.name == "reveal_solution":
        # Non-gated tiers are always permitted; gated reveal goes through the attempt-gate.
        allowed, msg = reveal_gate(convo.attempt_logged) if tier == "gated" else (True, "ok")
        emit(f"tool:reveal_solution:{'allowed' if allowed else 'blocked'}")
        return allowed, msg

    emit(f"tool:{call.name}:unknown")
    return False, f"unknown tool {call.name}"
