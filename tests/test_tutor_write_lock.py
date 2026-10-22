"""The tutor never holds SQLite's write lock across a model call (F5).

A pending AgentEvent flushed by a lazy load (e.g. `convo.messages` while building the
history) opens a write transaction; if that spans `llm.complete`, every other writer — the
usage rows the call itself records included — waits on it. These tests run the tutor on a
file-backed db and, from inside the model call, try to take the write lock on a second
connection with no wait.
"""

import json
import sqlite3

import pytest
from sqlmodel import Session, SQLModel, create_engine

from adaptive_academy.db import ensure_fts
from adaptive_academy.llm.types import LLMResponse, ToolCall
from adaptive_academy.models import Concept, Conversation, KnowledgeEstimate, Topic, Track


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


@pytest.fixture
def file_engine(tmp_path):
    path = tmp_path / "tutor.db"
    engine = create_engine(f"sqlite:///{path}",
                           connect_args={"check_same_thread": False, "timeout": 1})
    SQLModel.metadata.create_all(engine)
    ensure_fts(engine)
    yield engine, path
    engine.dispose()


def _write_lock_free(path) -> bool:
    conn = sqlite3.connect(path, timeout=0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


class _ProbingLLM:
    def __init__(self, path, responses):
        self.path = path
        self.responses = list(responses)
        self.lock_free: list[bool] = []

    def complete(self, system, messages, tools):
        self.lock_free.append(_write_lock_free(self.path))
        return self.responses.pop(0)


def test_no_write_lock_is_held_during_any_tutor_model_call(file_engine):
    from adaptive_academy.engine.tutor import run_tutor_turn

    engine, path = file_engine
    with Session(engine) as session:
        convo = _seed(session)
        llm = _ProbingLLM(path, [
            LLMResponse(tool_calls=[ToolCall(id="t1", name="reveal_solution",
                                             input={"text": "BLOCKED?"})]),
            LLMResponse(text="Why divide at all?"),
        ])
        # A submitted attempt: the solution guard's attempt check, a model call too, finds
        # no attempt, so the reveal is blocked and the reply is reviewed (a third call).
        verdict = LLMResponse(text=json.dumps(
            {"gives_away_solution": False, "learner_attempted": False, "reason": "r"}))
        guard = _ProbingLLM(path, [verdict, verdict])
        result = run_tutor_turn(session, convo, "is it softmax?", llm, guard_llm=guard,
                                attempt=True)

        assert llm.lock_free == [True, True]
        assert guard.lock_free == [True, True]
        assert result.reply == "Why divide at all?"
        kinds = [e.kind for e in result.events]
        assert kinds.count("llm_call") == 2  # the trace is still written
        assert "attempt:rejected" in kinds


def test_tutor_events_are_persisted_after_the_turn(file_engine):
    from sqlmodel import select

    from adaptive_academy.engine.tutor import run_tutor_turn
    from adaptive_academy.models import AgentEvent

    engine, path = file_engine
    with Session(engine) as session:
        convo = _seed(session)
        llm = _ProbingLLM(path, [LLMResponse(text="Try writing the denominator first.")])
        run_tutor_turn(session, convo, "how?", llm)
        convo_id = convo.id
    with Session(engine) as fresh:
        kinds = [e.kind for e in fresh.exec(
            select(AgentEvent).where(AgentEvent.conversation_id == convo_id)).all()]
    assert "levels" in kinds and "llm_call" in kinds


def test_no_write_lock_is_held_during_the_agent_sdk_tutor_run(file_engine, monkeypatch):
    import adaptive_academy.engine.tutor_sdk as tutor_sdk

    engine, path = file_engine
    probes: list[bool] = []

    class _Result:
        def __init__(self, result):
            self.result = result
            self.is_error = False

    async def fake_query(prompt, options):
        probes.append(_write_lock_free(path))
        yield _Result("Try the denominator first.")

    monkeypatch.setattr(tutor_sdk, "ResultMessage", _Result)
    monkeypatch.setattr(tutor_sdk, "query", fake_query)
    monkeypatch.setattr(tutor_sdk, "record_sdk_result", lambda *a, **kw: None)
    with Session(engine) as session:
        convo = _seed(session)
        out = tutor_sdk.run_tutor_turn_sdk(session, convo, "how?")
    assert probes == [True]
    assert out.reply == "Try the denominator first."
