import adaptive_academy.engine.tutor_sdk as mod
from adaptive_academy.engine.tools import reveal_gate
from adaptive_academy.engine.tutor_sdk import format_history, run_tutor_turn_sdk
from adaptive_academy.models import (
    Concept, Conversation, KnowledgeEstimate, Message, Topic, Track,
)


def test_reveal_gate_blocks_before_attempt_allows_after():
    allowed, msg = reveal_gate(False)
    assert allowed is False and "BLOCKED" in msg
    allowed, _ = reveal_gate(True)
    assert allowed is True


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
