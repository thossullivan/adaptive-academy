"""No engine path may hold the SQLite write lock across a researcher or LLM call.

UAT 2026-08-28 (F5): a Map Revision run held the RESERVED lock for over a minute, so
every memory search returned 500 "database is locked" and reindex returned 409. These
tests probe the lock from a second connection *inside* the scripted LLM / researcher
call; `BEGIN IMMEDIATE` fails within the probe timeout if the engine holds it.
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine

from adaptive_academy import db
from adaptive_academy.engine import scout
from adaptive_academy.engine.curriculum import generate_curriculum
from adaptive_academy.engine.research import research_topic
from adaptive_academy.engine.revision import run_revision
from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Milestone,
    Program,
    ProgramIntent,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
)


class LockProbe:
    """Records whether a second connection could take the write lock at call time."""

    def __init__(self, path: str):
        self.path = path
        self.results: list[bool] = []

    def __call__(self) -> None:
        conn = sqlite3.connect(self.path, timeout=0.2)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
            self.results.append(True)
        except sqlite3.OperationalError:
            self.results.append(False)
        finally:
            conn.close()

    @property
    def held(self) -> bool:
        return not all(self.results)


class ProbingLLM(ScriptedLLMClient):
    def __init__(self, responses, probe: LockProbe):
        super().__init__(responses)
        self.probe = probe

    def complete(self, system, messages, tools) -> LLMResponse:
        self.probe()
        return super().complete(system, messages, tools)


class ProbingResearcher:
    def __init__(self, probe: LockProbe):
        self.probe = probe

    def search(self, brief: SearchBrief) -> list[RawSource]:
        self.probe()
        return [RawSource(title=f"{brief.angle} source", url=f"https://e.com/{brief.angle}", tier=1)]


@pytest.fixture
def file_session(tmp_path):
    path = str(tmp_path / "lock.db")
    engine = create_engine(f"sqlite:///{path}", connect_args=db.CONNECT_ARGS)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    db.ensure_fts(engine)
    with Session(engine) as s:
        yield s, LockProbe(path)


def test_engine_connect_args_set_a_generous_busy_timeout(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args=db.CONNECT_ARGS)
    conn = engine.raw_connection()
    try:
        (busy_ms,) = conn.execute("PRAGMA busy_timeout").fetchone()  # type: ignore[attr-defined]
    finally:
        conn.close()
    assert busy_ms == db.SQLITE_BUSY_TIMEOUT_S * 1000
    assert db.SQLITE_BUSY_TIMEOUT_S >= 30


def test_run_revision_releases_write_lock_before_research_and_llm(file_session):
    session, probe = file_session
    program = Program(title="PhD prep", goal_statement="research-ready")
    session.add(program)
    session.commit()
    intent = ProgramIntent(program_id=program.id, focus_area="custom LLMs")
    session.add(intent)
    session.add(Milestone(program_id=program.id, title="Foundations", order_index=0))
    session.commit()

    llm = ProbingLLM(
        [LLMResponse(text=json.dumps({"map_health": "fine", "changes": []}))], probe
    )
    result = run_revision(session, program, intent, researcher=ProbingResearcher(probe), llm=llm)

    assert result.revision.map_health == "fine"
    assert len(probe.results) >= 2, "probe must run inside research and inside the LLM call"
    assert not probe.held, f"write lock held during network calls: {probe.results}"


def test_research_topic_releases_write_lock_before_fan_out_and_synthesis(file_session):
    session, probe = file_session
    topic = Topic(title="Graph memory")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="build graph memory systems")
    session.add(intent)
    session.commit()

    llm = ProbingLLM(
        [LLMResponse(text=json.dumps(
            {"overview": "Overview", "key_concepts": ["retrieval"], "prerequisite_map": {}}
        ))],
        probe,
    )
    from adaptive_academy.llm.scripted_retriever import ScriptedRetriever

    research_topic(
        session, topic, intent, researcher=ProbingResearcher(probe), llm=llm,
        retriever=ScriptedRetriever({}),
    )

    assert len(probe.results) >= 2
    assert not probe.held, f"write lock held during network calls: {probe.results}"


def test_generate_curriculum_releases_write_lock_before_llm(file_session):
    session, probe = file_session
    topic = Topic(title="Transformers")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="Build a transformer")
    foundation = TopicFoundation(
        topic_id=topic.id, key_concepts=["Attention"], prerequisite_map={}
    )
    source = SourceDoc(
        topic_id=topic.id, title="Attention", url="https://example.test/a", status="accepted"
    )
    session.add_all([intent, foundation, source])
    session.commit()

    llm = ProbingLLM([LLMResponse(text=json.dumps({"overview": "A path", "phases": []}))], probe)
    generate_curriculum(session, topic, intent, foundation, [source], llm=llm)

    assert probe.results == [True]


def test_scout_rank_releases_write_lock_before_llm(file_session):
    session, probe = file_session
    program = Program(title="PhD prep", goal_statement="research-ready")
    session.add(program)
    session.commit()
    candidates = [
        scout.Candidate(
            kind="orphan_note",
            label="Calculus for AI",
            evidence=[{"kind": "chunk", "ref": "file:///v/calc.md"}],
            weight=1.0,
        )
    ]
    llm = ProbingLLM([LLMResponse(text=json.dumps({"items": []}))], probe)
    scout.rank(session, program, candidates, llm=llm)

    assert probe.results == [True]


def test_search_survives_a_locked_trace_write(session, memory_api_client):
    """The memory:retrieve trace is best-effort: a locked DB must not turn hits into a 500."""
    client, topic = memory_api_client
    calls = {"n": 0}
    real_commit = session.commit

    def flaky_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("COMMIT", {}, sqlite3.OperationalError("database is locked"))
        real_commit()

    session.commit = flaky_commit  # type: ignore[method-assign]
    try:
        response = client.get("/api/memory/search", params={"q": "attention", "topic_id": topic.id})
    finally:
        session.commit = real_commit  # type: ignore[method-assign]
    assert response.status_code == 200
    assert response.json() == {"hits": []}


@pytest.fixture
def memory_api_client(session):
    from fastapi.testclient import TestClient

    from adaptive_academy.api.app import create_app
    from adaptive_academy.api.deps import get_retriever, get_session
    from adaptive_academy.llm.scripted_retriever import ScriptedRetriever

    topic = Topic(title="Memory API")
    session.add(topic)
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_retriever] = lambda: ScriptedRetriever({})
    client = TestClient(app)
    yield client, topic
    app.dependency_overrides.clear()
