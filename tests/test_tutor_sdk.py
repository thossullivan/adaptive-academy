import json
import types

import adaptive_academy.engine.tutor_sdk as mod
from adaptive_academy.engine.solution_guard import ATTEMPT_REJECTED, SolutionGuard
from adaptive_academy.engine.tools import reveal_gate
from adaptive_academy.engine.tutor_sdk import (
    format_history,
    log_attempt_result,
    reveal_solution_result,
    run_tutor_turn_sdk,
)
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Concept, Conversation, KnowledgeEstimate, Message, Topic, Track,
)


def test_reveal_gate_blocks_before_attempt_allows_after():
    allowed, msg = reveal_gate(False)
    assert allowed is False and "BLOCKED" in msg
    allowed, _ = reveal_gate(True)
    assert allowed is True


def test_reveal_handler_blocks_and_never_leaks_solution():
    # The load-bearing guardrail: with no attempt logged, the reveal tool returns a BLOCKED
    # is_error result and the solution text NEVER appears.
    convo = types.SimpleNamespace(attempt_logged=False)
    events = []
    out = reveal_solution_result(convo, lambda k, d="": events.append(k),
                                 {"text": "THE SECRET ANSWER IS 42"})
    assert out.get("is_error") is True
    blob = str(out["content"])
    assert "THE SECRET ANSWER IS 42" not in blob and "BLOCKED" in blob
    assert "tool:reveal_solution:blocked" in events


def _attempt_guard(emit, attempted: bool) -> SolutionGuard:
    verdict = {"gives_away_solution": False, "learner_attempted": attempted, "reason": "r"}
    return SolutionGuard(concept="calculus", learner_text="I used the chain rule because...",
                         llm=ScriptedLLMClient([LLMResponse(text=json.dumps(verdict))]),
                         emit=emit)


def test_log_attempt_then_reveal_allows_and_returns_solution():
    convo = types.SimpleNamespace(attempt_logged=False)
    events = []
    emit = lambda k, d="": events.append(k)  # noqa: E731
    out = log_attempt_result(convo, {"summary": "I tried the chain rule"},
                             guard=_attempt_guard(emit, True))
    assert "ok: attempt recorded" in str(out["content"])
    assert convo.attempt_logged is True
    out = reveal_solution_result(convo, emit, {"text": "THE SECRET ANSWER IS 42"})
    assert "is_error" not in out
    assert "THE SECRET ANSWER IS 42" in str(out["content"])
    assert "tool:log_attempt" in events and "tool:reveal_solution:allowed" in events


def test_log_attempt_without_a_real_attempt_keeps_the_reveal_blocked():
    convo = types.SimpleNamespace(attempt_logged=False)
    events = []
    emit = lambda k, d="": events.append(k)  # noqa: E731
    out = log_attempt_result(convo, {"summary": "they guessed 42"},
                             guard=_attempt_guard(emit, False))
    assert convo.attempt_logged is False
    assert ATTEMPT_REJECTED in str(out["content"])
    reveal = reveal_solution_result(convo, emit, {"text": "THE SECRET ANSWER IS 42"})
    assert reveal.get("is_error") is True and "THE SECRET ANSWER IS 42" not in str(reveal)
    assert "tool:log_attempt:rejected" in events and "tool:log_attempt" not in events


def _seed(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    session.refresh(convo)
    return convo


def test_format_history_role_labels(session):
    convo = _seed(session)
    session.add(Message(conversation_id=convo.id, role="user", content="hi"))
    session.add(Message(conversation_id=convo.id, role="tutor", content="hello"))
    session.commit()
    session.refresh(convo)
    h = format_history(convo)
    assert "Learner: hi" in h and "Tutor: hello" in h


class _FakeResult:
    def __init__(self, result, is_error=False):
        self.result = result
        self.is_error = is_error


def test_run_tutor_turn_sdk_persists_and_returns_reply(session, monkeypatch):
    convo = _seed(session)

    async def fake_query(prompt, options):
        # The flattened history (incl. the new user message) is in the prompt.
        assert "Learner: explain softmax" in prompt
        # Only the two tutor tools are exposed, permissions bypassed.
        assert options.allowed_tools == ["mcp__tutor__log_attempt", "mcp__tutor__reveal_solution"]
        assert options.permission_mode == "bypassPermissions"
        yield _FakeResult("Here's a hint about softmax.")

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)

    res = run_tutor_turn_sdk(session, convo, "explain softmax")
    assert res.reply == "Here's a hint about softmax."
    kinds = {e.kind for e in res.events}
    assert {"levels", "tutor:sdk"} <= kinds

    session.refresh(convo)
    assert [m.role for m in convo.messages] == ["user", "tutor"]
    assert convo.messages[-1].content == "Here's a hint about softmax."
