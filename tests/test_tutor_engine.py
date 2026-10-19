from adaptive_academy.engine.tutor import _FALLBACK, _MAX_STEPS, run_tutor_turn
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse, ToolCall
from adaptive_academy.models import (
    Concept,
    Conversation,
    KnowledgeEstimate,
    Topic,
    Track,
)


def _seed(session) -> Conversation:
    topic = Topic(title="LLMs")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="self-attention")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    return convo


def test_reveal_blocked_before_attempt(session):
    convo = _seed(session)
    # Model immediately tries to reveal the solution, then (after the block) gives a hint.
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="reveal_solution",
                                         input={"text": "FULL ANSWER 42"})]),
        LLMResponse(text="Here's a hint: what does softmax normalize over?"),
    ])
    result = run_tutor_turn(session, convo, "just give me the answer", llm)

    assert "FULL ANSWER 42" not in result.reply
    assert "hint" in result.reply.lower()
    assert convo.attempt_logged is False
    assert any("reveal_solution:blocked" in e.kind for e in result.events)


def test_attempt_then_reveal_allowed(session):
    convo = _seed(session)
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="log_attempt",
                                         input={"summary": "tried QK^T"})]),
        LLMResponse(tool_calls=[ToolCall(id="t2", name="reveal_solution",
                                         input={"text": "FULL ANSWER 42"})]),
        LLMResponse(text="Great — the full picture: FULL ANSWER 42"),
    ])
    result = run_tutor_turn(session, convo, "I think attention is softmax(QK^T)V", llm)

    assert convo.attempt_logged is True
    assert "FULL ANSWER 42" in result.reply
    assert any(e.kind == "tool:log_attempt" for e in result.events)


def test_plain_reply_persists_messages(session):
    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text="What do you already know about it?")])
    result = run_tutor_turn(session, convo, "teach me attention", llm)

    session.refresh(convo)
    roles = [(m.role, m.content) for m in convo.messages]
    assert roles[0] == ("user", "teach me attention")
    assert roles[1] == ("tutor", "What do you already know about it?")
    assert result.reply == "What do you already know about it?"
    # First call should include the computed levels in the system prompt (expert -> low/high)
    assert "Assistance level = low" in llm.calls[0]["system"]


def test_max_steps_exhaustion_falls_back(session):
    convo = _seed(session)
    # Model calls a tool on every step and never returns text -> loop exhausts.
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id=f"t{i}", name="log_attempt",
                                         input={"summary": "x"})])
        for i in range(_MAX_STEPS)
    ])
    result = run_tutor_turn(session, convo, "...", llm)

    assert result.reply == _FALLBACK
    assert any(e.kind == "max_steps_exhausted" for e in result.events)


def test_whitespace_only_reply_falls_back_to_a_non_empty_message(session):
    # A whitespace-only tutor message would be resent as an assistant turn next time, and
    # the API rejects empty / whitespace-only text content.
    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text="  \n", stop_reason="end_turn")])
    result = run_tutor_turn(session, convo, "hi", llm)
    assert result.reply == _FALLBACK
    session.refresh(convo)
    assert all(m.content.strip() for m in convo.messages)


def test_refusal_gives_a_legible_notice_not_partial_text(session):
    from adaptive_academy.engine.tutor import _REFUSAL

    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text="Partial ans", stop_reason="refusal")])
    result = run_tutor_turn(session, convo, "question", llm)
    assert result.reply == _REFUSAL
    assert "Partial ans" not in result.reply
    assert any(e.kind == "llm_refusal" for e in result.events)
    assert not any(e.kind == "max_steps_exhausted" for e in result.events)
