"""No engine path may hold the SQLite write lock across a researcher or LLM call.

UAT 2026-08-28 (F5): a Map Revision run held the RESERVED lock for over a minute, so
every memory search returned 500 "database is locked" and reindex returned 409. These
tests probe the lock from a second connection *inside* the scripted LLM / researcher
call; `BEGIN IMMEDIATE` fails within the probe timeout if the engine holds it.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from adaptive_academy import db
from adaptive_academy.engine import scout
from adaptive_academy.engine.trace_writer import TRACE_WRITER
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


def _hold_write_lock(path: str, seconds: float, held: threading.Event) -> threading.Thread:
    def _hold() -> None:
        conn = sqlite3.connect(path, timeout=1)
        conn.execute("BEGIN IMMEDIATE")
        held.set()
        time.sleep(seconds)
        conn.execute("ROLLBACK")
        conn.close()

    thread = threading.Thread(target=_hold, daemon=True)
    thread.start()
    return thread


def test_search_returns_hits_promptly_while_another_writer_holds_the_lock(file_session, tmp_path):
    """Real contention: a writer holds BEGIN IMMEDIATE for 3 s. The search must answer well
    inside that window (not wait on the 30 s busy timeout) and the trace row must still
    land once the lock is released."""
    from fastapi.testclient import TestClient

    from adaptive_academy.api.app import create_app
    from adaptive_academy.api.deps import get_retriever, get_session
    from adaptive_academy.engine.memory import index_text
    from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
    from adaptive_academy.models import AgentEvent, Chunk

    session, probe = file_session
    topic = Topic(title="Memory API")
    session.add(topic)
    session.commit()
    index_text(session, kind="vault_note", text="Attention is all you need.",
               source_ref="file:///vault/attention.md", doc_title="Attention",
               topic_id=topic.id, heading="Mechanism")
    session.commit()
    chunk_id = session.exec(select(Chunk)).first().id
    retriever = ScriptedRetriever({"attention": [chunk_id]})

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_retriever] = lambda: retriever
    client = TestClient(app)
    try:
        held = threading.Event()
        holder = _hold_write_lock(probe.path, 3.0, held)
        assert held.wait(2)
        started = time.perf_counter()
        response = client.get("/api/memory/search", params={"q": "attention", "topic_id": topic.id})
        elapsed = time.perf_counter() - started
        assert response.status_code == 200
        assert [hit["chunk_id"] for hit in response.json()["hits"]] == [chunk_id]
        assert elapsed < 1.5, f"search waited on the write lock: {elapsed:.1f}s"
        holder.join(5)
        assert TRACE_WRITER.flush(10)
        session.expire_all()
        kinds = [e.kind for e in session.exec(select(AgentEvent)).all()]
        assert "memory:retrieve" in kinds
    finally:
        app.dependency_overrides.clear()


def test_second_concurrent_revision_is_refused_while_first_is_in_flight(file_session):
    """Two requests, two sessions. The second must be refused while the first is inside its
    LLM call — the early commits released SQLite's lock, so the guard must be explicit."""
    from adaptive_academy.engine.runlock import RunInProgress
    from adaptive_academy.models import MapRevision

    session, probe = file_session
    program = Program(title="PhD prep", goal_statement="research-ready")
    session.add(program)
    session.commit()
    intent = ProgramIntent(program_id=program.id, focus_area="custom LLMs")
    session.add(intent)
    session.commit()
    program_id = program.id

    in_llm = threading.Event()
    release = threading.Event()

    class BlockingLLM(ScriptedLLMClient):
        def complete(self, system, messages, tools) -> LLMResponse:
            in_llm.set()
            assert release.wait(10)
            return super().complete(system, messages, tools)

    outcome: dict = {}

    def first_request() -> None:
        with Session(session.get_bind()) as other:
            prog = other.get(Program, program_id)
            intent_row = other.exec(
                select(ProgramIntent).where(ProgramIntent.program_id == program_id)
            ).first()
            llm = BlockingLLM(
                [LLMResponse(text=json.dumps({"map_health": "fine", "changes": []}))]
            )
            outcome["first"] = run_revision(
                other, prog, intent_row, researcher=ProbingResearcher(probe), llm=llm
            )

    worker = threading.Thread(target=first_request, daemon=True)
    worker.start()
    assert in_llm.wait(10)
    with pytest.raises(RunInProgress):
        run_revision(
            session, program, intent, researcher=ProbingResearcher(probe),
            llm=ScriptedLLMClient([LLMResponse(text=json.dumps({"map_health": "dup", "changes": []}))]),
        )
    release.set()
    worker.join(10)
    assert outcome["first"].revision.map_health == "fine"
    session.expire_all()
    revisions = session.exec(select(MapRevision).where(MapRevision.program_id == program_id)).all()
    assert len(revisions) == 1
    # a later, sequential run is allowed again
    run_revision(
        session, program, intent, researcher=ProbingResearcher(probe),
        llm=ScriptedLLMClient([LLMResponse(text=json.dumps({"map_health": "later", "changes": []}))]),
    )


def test_revision_rechecks_open_revision_after_the_llm_call(file_session):
    """If an open revision appears while the LLM call runs (another process), the run must
    abort without persisting a second MapRevision."""
    from adaptive_academy.models import MapChange, MapRevision

    session, probe = file_session
    program = Program(title="PhD prep", goal_statement="research-ready")
    session.add(program)
    session.commit()
    intent = ProgramIntent(program_id=program.id, focus_area="custom LLMs")
    session.add(intent)
    session.commit()
    program_id = program.id

    class InterferingLLM(ScriptedLLMClient):
        def complete(self, system, messages, tools) -> LLMResponse:
            with Session(session.get_bind()) as other:
                rev = MapRevision(program_id=program_id, map_health="elsewhere")
                other.add(rev)
                other.flush()
                other.add(MapChange(revision_id=rev.id, kind="add_topic",
                                    payload={"title": "X"}, why="", source_urls=[]))
                other.commit()
            return super().complete(system, messages, tools)

    llm = InterferingLLM([LLMResponse(text=json.dumps({"map_health": "mine", "changes": []}))])
    with pytest.raises(ValueError, match="open revision"):
        run_revision(session, program, intent, researcher=ProbingResearcher(probe), llm=llm)
    session.expire_all()
    healths = [r.map_health for r in session.exec(
        select(MapRevision).where(MapRevision.program_id == program_id)).all()]
    assert healths == ["elsewhere"]


def _search_app(session, retriever):
    from fastapi.testclient import TestClient

    from adaptive_academy.api.app import create_app
    from adaptive_academy.api.deps import get_retriever, get_session

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_retriever] = lambda: retriever
    return app, TestClient(app)


def test_many_searches_during_a_long_write_lock_do_not_exhaust_the_pool(file_session):
    """Round-2 review: a thread per search could park up to the pool capacity (5 + 10
    overflow) on the busy timeout and starve the next read. With one bounded writer,
    20 searches during a 3 s lock each answer promptly and every trace still lands."""
    from adaptive_academy.engine.memory import index_text
    from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
    from adaptive_academy.models import AgentEvent, Chunk

    session, probe = file_session
    topic = Topic(title="Memory API")
    session.add(topic)
    session.commit()
    index_text(session, kind="vault_note", text="Attention is all you need.",
               source_ref="file:///vault/attention.md", doc_title="Attention",
               topic_id=topic.id, heading="Mechanism")
    session.commit()
    chunk_id = session.exec(select(Chunk)).first().id
    app, client = _search_app(session, ScriptedRetriever({"attention": [chunk_id]}))
    before = TRACE_WRITER.dropped
    try:
        held = threading.Event()
        holder = _hold_write_lock(probe.path, 3.0, held)
        assert held.wait(2)
        n = 20
        started = time.perf_counter()
        for _ in range(n):
            response = client.get(
                "/api/memory/search", params={"q": "attention", "topic_id": topic.id}
            )
            assert response.status_code == 200
            assert len(response.json()["hits"]) == 1
        elapsed = time.perf_counter() - started
        assert elapsed < 2.5, f"{n} searches took {elapsed:.1f}s under a held write lock"
        holder.join(5)
        assert TRACE_WRITER.flush(20)
        assert TRACE_WRITER.dropped == before
        session.expire_all()
        traces = [e for e in session.exec(select(AgentEvent)).all() if e.kind == "memory:retrieve"]
        assert len(traces) == n
    finally:
        app.dependency_overrides.clear()


def _blocking_llm(response_text: str, in_llm: threading.Event, release: threading.Event):
    class BlockingLLM(ScriptedLLMClient):
        def complete(self, system, messages, tools) -> LLMResponse:
            in_llm.set()
            assert release.wait(10)
            return super().complete(system, messages, tools)

    return BlockingLLM([LLMResponse(text=response_text)])


def test_second_concurrent_curriculum_generation_is_refused(file_session):
    from adaptive_academy.engine.runlock import RunInProgress
    from adaptive_academy.models import Track

    session, _probe = file_session
    topic = Topic(title="Transformers")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="Build a transformer")
    foundation = TopicFoundation(topic_id=topic.id, key_concepts=["Attention"], prerequisite_map={})
    source = SourceDoc(topic_id=topic.id, title="A", url="https://example.test/a", status="accepted")
    session.add_all([intent, foundation, source])
    session.commit()
    topic_id = topic.id
    in_llm, release = threading.Event(), threading.Event()
    payload = json.dumps({"overview": "A path", "phases": []})

    def first() -> None:
        with Session(session.get_bind()) as other:
            t = other.get(Topic, topic_id)
            i = other.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
            f = other.exec(select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)).first()
            srcs = other.exec(select(SourceDoc).where(SourceDoc.topic_id == topic_id)).all()
            generate_curriculum(other, t, i, f, list(srcs), llm=_blocking_llm(payload, in_llm, release))

    worker = threading.Thread(target=first, daemon=True)
    worker.start()
    assert in_llm.wait(10)
    with pytest.raises(RunInProgress):
        generate_curriculum(session, topic, intent, foundation, [source],
                            llm=ScriptedLLMClient([LLMResponse(text=payload)]))
    release.set()
    worker.join(10)
    session.expire_all()
    assert len(session.exec(select(Track).where(Track.topic_id == topic_id)).all()) == 1


def test_second_concurrent_scout_run_is_refused(file_session):
    from adaptive_academy.engine.runlock import RunInProgress
    from adaptive_academy.models import TopicSuggestion

    session, _probe = file_session
    program = Program(title="PhD prep", goal_statement="research-ready")
    session.add(program)
    session.commit()
    program_id = program.id
    in_llm, release = threading.Event(), threading.Event()
    payload = json.dumps({"items": []})

    def first() -> None:
        with Session(session.get_bind()) as other:
            p = other.get(Program, program_id)
            # force a ranking call: one candidate via a monkeypatched generator
            scout.run_scout(other, p, llm=_blocking_llm(payload, in_llm, release))

    orig = scout.orphan_note_candidates
    scout.orphan_note_candidates = lambda session, deadline=None: [
        scout.Candidate(kind="orphan_note", label="Calculus for AI",
                        evidence=[{"kind": "chunk", "ref": "file:///v/calc.md"}], weight=1.0)
    ]
    try:
        worker = threading.Thread(target=first, daemon=True)
        worker.start()
        assert in_llm.wait(10)
        with pytest.raises(RunInProgress):
            scout.run_scout(session, program, llm=ScriptedLLMClient([LLMResponse(text=payload)]))
        release.set()
        worker.join(10)
    finally:
        scout.orphan_note_candidates = orig
    session.expire_all()
    assert session.exec(select(TopicSuggestion).where(TopicSuggestion.program_id == program_id)).all() == []


def test_research_rerun_is_refused_before_any_paid_work(file_session):
    session, probe = file_session
    topic = Topic(title="Graph memory")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="build graph memory systems")
    session.add(intent)
    session.add(TopicFoundation(topic_id=topic.id, overview="done", key_concepts=[], prerequisite_map={}))
    # With no sources a rerun is allowed (test_api_research.py); with a reading list it isn't.
    session.add(SourceDoc(topic_id=topic.id, title="Paper", url="https://e.com/p"))
    session.commit()

    from adaptive_academy.engine.research import ResearchAlreadyDone

    llm = ProbingLLM([LLMResponse(text="{}")], probe)
    with pytest.raises(ResearchAlreadyDone, match="already has a foundation"):
        research_topic(session, topic, intent, researcher=ProbingResearcher(probe), llm=llm)
    assert probe.results == [], "no researcher or LLM call may run"
    assert not issubclass(ResearchAlreadyDone, ValueError), "must not shadow JSONDecodeError"


def _research_client(session, llm, researcher):
    from fastapi.testclient import TestClient

    from adaptive_academy.api.app import create_app
    from adaptive_academy.api.deps import get_llm, get_researcher, get_retriever, get_session
    from adaptive_academy.llm.scripted_retriever import ScriptedRetriever

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_researcher] = lambda: researcher
    app.dependency_overrides[get_retriever] = lambda: ScriptedRetriever({})
    return app, TestClient(app, raise_server_exceptions=False)


def test_research_route_keeps_502_for_malformed_model_json_and_409_for_rerun(file_session):
    """Round-3 review: a broad `except ValueError` turned json.JSONDecodeError (malformed
    model output, which has a 502 handler) into a 409 state conflict."""
    session, probe = file_session
    topic = Topic(title="Graph memory")
    session.add(topic)
    session.commit()
    session.add(TopicIntent(topic_id=topic.id, goal="build graph memory systems"))
    session.commit()

    bad_llm = ScriptedLLMClient([LLMResponse(text='{"overview": "truncated"')])
    app, client = _research_client(session, bad_llm, ProbingResearcher(probe))
    try:
        response = client.post(f"/api/topics/{topic.id}/research")
        assert response.status_code == 502, response.text
    finally:
        app.dependency_overrides.clear()
    session.rollback()

    session.add(TopicFoundation(topic_id=topic.id, overview="done", key_concepts=[], prerequisite_map={}))
    session.add(SourceDoc(topic_id=topic.id, title="Paper", url="https://e.com/p"))
    session.commit()
    app, client = _research_client(session, bad_llm, ProbingResearcher(probe))
    try:
        response = client.post(f"/api/topics/{topic.id}/research")
        assert response.status_code == 409
        assert "already has a foundation" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_trace_writer_survives_a_failing_batch_and_keeps_writing(file_session):
    """Round-3 review: a non-OperationalError (here an FK IntegrityError) must not kill the
    sole writer thread or strand the batches queued behind it."""
    from adaptive_academy.engine.trace_writer import TraceWriter
    from adaptive_academy.models import AgentEvent

    session, _probe = file_session
    bind = session.get_bind()
    writer = TraceWriter()
    bad = [AgentEvent(topic_id=999_999, kind="memory:retrieve", detail="dangling fk")]
    good = [AgentEvent(kind="memory:retrieve", detail="fine")]
    assert writer.submit(bind, bad)
    assert writer.submit(bind, good)
    assert writer.submit(bind, [AgentEvent(kind="memory:retrieve", detail="also fine")])
    assert writer.flush(10), "queue must drain even after a failing batch"
    assert writer.alive
    assert writer.dropped == 1
    assert writer.written == 2
    session.expire_all()
    details = sorted(e.detail for e in session.exec(select(AgentEvent)).all() if e.kind == "memory:retrieve")
    assert details == ["also fine", "fine"]


def test_review_sources_releases_write_lock_before_fetching_sources(file_session):
    """UAT: saving a 12-source reading list held the write lock for ~2 minutes of fetching
    and embedding, so a second save got 500 "database is locked". The statuses must be
    committed, and the lock free, while a source is being fetched."""
    from fastapi.testclient import TestClient

    from adaptive_academy.api.app import create_app
    from adaptive_academy.api.deps import get_fetcher, get_session
    from adaptive_academy.models import Chunk

    session, probe = file_session
    topic = Topic(title="Reading list")
    session.add(topic)
    session.commit()
    docs = [SourceDoc(topic_id=topic.id, title=f"S{i}", url=f"https://e.com/{i}") for i in range(2)]
    session.add_all(docs)
    session.commit()
    seen_status: list[str] = []

    def probing_fetch(url: str) -> str:
        probe()
        conn = sqlite3.connect(probe.path, timeout=0.2)
        try:
            seen_status.append(conn.execute(
                "SELECT status FROM sourcedoc WHERE url = ?", (url,)).fetchone()[0])
        finally:
            conn.close()
        return "Fetched source text."

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_fetcher] = lambda: probing_fetch
    try:
        response = TestClient(app).post(
            f"/api/topics/{topic.id}/sources/review",
            json={"accepted_ids": [d.id for d in docs], "pruned_ids": []},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(probe.results) == 2
    assert not probe.held, "review held the SQLite write lock across a source fetch"
    assert seen_status == ["accepted", "accepted"]
    session.expire_all()
    assert len(session.exec(select(Chunk)).all()) == 2


def test_trace_writer_staticpool_path_never_raises(session):
    """The inline (StaticPool) path must not turn a trace failure into a request failure."""
    from adaptive_academy.engine.trace_writer import TraceWriter
    from adaptive_academy.models import AgentEvent

    writer = TraceWriter()
    assert writer.submit(session.get_bind(), [AgentEvent(topic_id=999_999, kind="memory:retrieve", detail="x")])
    assert writer.dropped == 1
    assert writer.submit(session.get_bind(), [AgentEvent(kind="memory:retrieve", detail="ok")])
    assert writer.written == 1
