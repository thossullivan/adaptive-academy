"""A revealed worked solution is marked in storage (Message.reveals_solution), so the
notebook can list it. Before this, an allowed reveal was stored as a plain tutor message,
indistinguishable from a hint. Both tutor paths; all model calls scripted."""

import json

from sqlmodel import select

import adaptive_academy.engine.tutor_sdk as tutor_sdk
from adaptive_academy.engine.tutor import run_tutor_turn
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse, ToolCall
from adaptive_academy.models import Concept, Conversation, KnowledgeEstimate, Message, Topic, Track

SECRET = "Worked solution: softmax(QK^T / sqrt(d_k)) V"
HINT = "What does each row of QK^T measure?"
REAL = "I'd divide by sqrt(d_k) because the variance grows with dimension"


def _seed(session, *, attempt_logged):
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
    convo = Conversation(topic_id=topic.id, concept_id=concept.id, attempt_logged=attempt_logged)
    session.add(convo)
    session.commit()
    return convo


def _verdict(*, attempted):
    return LLMResponse(text=json.dumps({"gives_away_solution": False,
                                        "learner_attempted": attempted, "reason": "r"}))


def _tutor_messages(session, convo):
    session.expire_all()
    return session.exec(select(Message).where(Message.conversation_id == convo.id,
                                              Message.role == "tutor")
                        .order_by(Message.id)).all()


def test_an_allowed_reveal_is_marked(session):
    convo = _seed(session, attempt_logged=True)
    llm = ScriptedLLMClient([LLMResponse(tool_calls=[
        ToolCall(id="t1", name="reveal_solution", input={"text": SECRET})])])
    run_tutor_turn(session, convo, "show me", llm, guard_llm=ScriptedLLMClient([]))
    [reply] = _tutor_messages(session, convo)
    assert reply.content == SECRET and reply.reveals_solution is True


def test_a_blocked_reveal_and_a_hint_are_not_marked(session):
    convo = _seed(session, attempt_logged=False)
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="reveal_solution",
                                         input={"text": SECRET})]),
        LLMResponse(text=HINT),
    ])
    run_tutor_turn(session, convo, "tell me", llm,
                   guard_llm=ScriptedLLMClient([_verdict(attempted=False)]))
    [reply] = _tutor_messages(session, convo)
    assert reply.content == HINT and reply.reveals_solution is None


class _FakeResult:
    def __init__(self, result, is_error=False):
        self.result = result
        self.is_error = is_error


def _sdk_turn(session, monkeypatch, *, attempt_logged):
    convo = _seed(session, attempt_logged=attempt_logged)
    captured: dict = {}
    real_server = tutor_sdk.create_sdk_mcp_server

    def capture_server(name, tools):
        captured.update({t.name: t for t in tools})
        return real_server(name, tools=tools)

    async def fake_query(prompt, options):
        revealed = await captured["reveal_solution"].handler({"text": SECRET})
        yield _FakeResult(SECRET if not revealed.get("is_error") else HINT)

    monkeypatch.setattr(tutor_sdk, "create_sdk_mcp_server", capture_server)
    monkeypatch.setattr(tutor_sdk, "ResultMessage", _FakeResult)
    monkeypatch.setattr(tutor_sdk, "query", fake_query)
    monkeypatch.setattr(tutor_sdk, "record_sdk_result", lambda *a, **kw: None)
    tutor_sdk.run_tutor_turn_sdk(session, convo, REAL,
                                 guard_llm=ScriptedLLMClient([_verdict(attempted=False)]))
    return convo


def test_sdk_an_allowed_reveal_is_marked(session, monkeypatch):
    convo = _sdk_turn(session, monkeypatch, attempt_logged=True)
    [reply] = _tutor_messages(session, convo)
    assert reply.content == SECRET and reply.reveals_solution is True


def test_sdk_a_blocked_reveal_is_not_marked(session, monkeypatch):
    convo = _sdk_turn(session, monkeypatch, attempt_logged=False)
    [reply] = _tutor_messages(session, convo)
    assert reply.reveals_solution is None
