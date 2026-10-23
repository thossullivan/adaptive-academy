"""Deleting a topic (engine/topics.py `delete_topic`, DELETE /api/topics/{id}).

A real topic owns more than the demo: memory chunks with FTS5 and sqlite-vec entries, vault
notes it indexed, concept aliases and edges into other topics, and a program milestone slot.
Its own rows go; what a program owns stays; cost history stays; files on disk stay.
"""

import importlib.util
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.db import ensure_fts, ensure_vec
from adaptive_academy.demo import build_demo, remove_demo
from adaptive_academy.engine.memory import (
    index_assessment,
    index_paper,
    index_roleplay_turn,
    index_text,
    split_markdown,
)
from adaptive_academy.engine.runlock import exclusive_run
from adaptive_academy.engine.topics import delete_topic, owned_rows
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.llm.hybrid_retriever import HybridRetriever
from adaptive_academy.llm.scripted_embedder import ScriptedEmbedder
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Chunk,
    ChunkConcept,
    Concept,
    ConceptAlias,
    ConceptEdge,
    ConceptNote,
    Conversation,
    LLMUsage,
    Message,
    Milestone,
    PaperProbe,
    Program,
    ProgramTopicLink,
    RoleplaySession,
    RoleplayTurn,
    SourceDoc,
    Topic,
    Track,
    VaultLink,
)

NOW = datetime(2026, 10, 19, 15, 30, 0)
HAS_VEC = importlib.util.find_spec("sqlite_vec") is not None


def _vec_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    assert ensure_fts(engine) is True
    assert ensure_vec(engine) is True
    return Session(engine)


@pytest.fixture
def vec_session():
    if not HAS_VEC:
        pytest.skip("sqlite-vec optional extra is unavailable")
    with _vec_session() as session:
        yield session


def _concepts(session: Session, topic_id: int) -> list[Concept]:
    return list(session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id).order_by(Concept.id)
    ).all())


def _fts_ids(session: Session, query: str) -> set[int]:
    return {r[0] for r in session.execute(
        text("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH :q"), {"q": query}).all()}


def _vec_ids(session: Session) -> set[int]:
    return {r[0] for r in session.execute(text("SELECT chunk_id FROM chunk_vec")).all()}


def _real_topic(session: Session, title: str) -> Topic:
    """The demo builder's few weeks of use, as an ordinary (non-demo) topic."""
    topic = build_demo(session, now=NOW)
    topic.is_demo = False
    topic.title = title
    session.add(topic)
    session.commit()
    return topic


class Populated:
    """Everything a real topic touches beyond what the demo builder writes."""

    def __init__(self, session: Session, tmp_path, retriever: HybridRetriever | None):
        self.control = _real_topic(session, "Linear algebra")
        self.topic = _real_topic(session, "Bayesian A/B testing")
        tid = self.tid = self.topic.id
        concepts = _concepts(session, tid)
        control_concepts = _concepts(session, self.control.id)
        self.concept = concepts[0]

        # A program whose milestone started this topic.
        self.program = Program(title="Stats PhD prep")
        session.add(self.program)
        session.flush()
        self.milestone = Milestone(program_id=self.program.id, title="Inference")
        session.add(self.milestone)
        session.flush()
        self.link = ProgramTopicLink(milestone_id=self.milestone.id, topic_id=tid,
                                     status="started", proposed_title="Bayesian A/B testing")
        session.add(self.link)
        session.add(ConceptAlias(program_id=self.program.id, canonical_name="prior",
                                 concept_id=self.concept.id))
        # A cross-topic edge: it must go with the concept, not dangle.
        session.add(ConceptEdge(src_concept_id=self.concept.id,
                                dst_concept_id=control_concepts[0].id,
                                kind="related", origin="alias"))
        noted = set(session.exec(select(ConceptNote.concept_id)).all())
        session.add(ConceptNote(concept_id=next(c.id for c in concepts if c.id not in noted),
                                body="my own words"))

        # Program-owned content filed under the topic in the memory index.
        self.probe = PaperProbe(program_id=self.program.id, milestone_id=self.milestone.id,
                                paper_title="Sequential testing",
                                paper_text="# Sequential\n\nzebraquant paper body text")
        session.add(self.probe)
        self.roleplay = RoleplaySession(program_id=self.program.id,
                                        milestone_id=self.milestone.id)
        session.add(self.roleplay)
        session.flush()
        index_paper(session, self.probe, retriever=retriever)
        turn = RoleplayTurn(session_id=self.roleplay.id, role="user",
                            content="okapiturn my answer to the persona")
        session.add(turn)
        session.flush()
        index_roleplay_turn(session, turn, topic_id=tid, concept_ids=[self.concept.id],
                            retriever=retriever)
        # A roleplay grade on the topic's concept: the topic's evidence, so it goes.
        graded = Assessment(concept_id=self.concept.id, kind="roleplay", prompt="persona q",
                            response="answer", score=0.7, roleplay_session_id=self.roleplay.id)
        session.add(graded)
        session.flush()
        index_assessment(session, graded, topic_id=tid, retriever=retriever)

        # A vault note the topic indexed, with a wikilink. The file must survive.
        self.note_path = tmp_path / "Priors.md"
        self.note_path.write_text("# Priors\n\nquokkanote see [[Posterior]]\n")
        self.note_ref = self.note_path.resolve().as_uri()
        index_text(session, kind="vault_note", text=self.note_path.read_text(),
                   source_ref=self.note_ref, doc_title="Priors", topic_id=tid,
                   splitter=split_markdown, retriever=retriever)
        session.add(VaultLink(src_ref=self.note_ref, dst_ref="", dst_title="Posterior"))
        session.add(SourceDoc(topic_id=tid, title="Priors", url=self.note_ref,
                              status="accepted", added_by="vault"))

        # Searchable text of the topic's own, and of the other topic.
        index_text(session, kind="learner_output", text="wombatword learner text",
                   source_ref="test:topic", topic_id=tid, concept_id=self.concept.id,
                   retriever=retriever)
        index_text(session, kind="learner_output", text="narwhalword control text",
                   source_ref="test:control", topic_id=self.control.id,
                   concept_id=control_concepts[0].id, retriever=retriever)

        # Cost history, which has no topic column.
        session.add(LLMUsage(backend="anthropic", model="claude-sonnet", operation="complete",
                             cost_usd=0.25))
        session.commit()

        if retriever is not None:
            # The demo builder indexes without a retriever: embed every chunk now, so every
            # chunk of the topic has a real vector row.
            ids = [c.id for c in session.exec(select(Chunk)).all()]
            retriever.on_index(session, ids)
            session.commit()


def _assert_deleted(session: Session, data: Populated, owned_before: dict, chunk_ids: set[int]):
    tid = data.tid
    session.expire_all()
    assert session.get(Topic, tid) is None
    # Every row the topic owned is gone, table by table, except what a program owns: the
    # milestone slot and the chunks of its paper and roleplay (checked below).
    program_chunks = {c.id for c in session.exec(select(Chunk).where(
        Chunk.source_ref.startswith("paperprobe:")
        | Chunk.source_ref.startswith("roleplayturn:"))).all()}
    for table, ids in owned_before.items():
        if table.name == "programtopiclink":
            continue
        if table.name == "chunk":
            ids = ids - program_chunks
        left = session.execute(
            select(table.c.id).where(table.c.id.in_(ids))).scalars().all()
        assert left == [], f"{table.name} kept rows {left}"
    assert session.exec(select(Chunk).where(Chunk.topic_id == tid)).all() == []
    assert not session.exec(select(Chunk).where(Chunk.id.in_(chunk_ids))).all()

    # The FTS index forgot the topic's text and still finds the other topic's.
    assert _fts_ids(session, "wombatword") == set()
    assert _fts_ids(session, "quokkanote") == set()
    assert _fts_ids(session, "narwhalword")
    session.execute(text("INSERT INTO chunk_fts(chunk_fts, rank) VALUES('integrity-check', 1)"))

    # The program keeps its milestone slot as a stub that can be started again.
    link = session.get(ProgramTopicLink, data.link.id)
    assert link is not None and link.topic_id is None and link.status == "stub"
    assert session.get(Program, data.program.id) is not None
    assert session.get(Milestone, data.milestone.id) is not None
    events = session.exec(select(AgentEvent).where(
        AgentEvent.program_id == data.program.id,
        AgentEvent.kind == "program:topic_deleted")).all()
    assert len(events) == 1 and "Bayesian A/B testing" in events[0].detail

    # The paper and the roleplay outlive the topic, and so do their chunks, detached.
    assert session.get(PaperProbe, data.probe.id) is not None
    assert session.get(RoleplaySession, data.roleplay.id) is not None
    assert len(session.exec(select(RoleplayTurn)).all()) == 1
    for prefix in ("paperprobe:", "roleplayturn:"):
        kept = session.exec(select(Chunk).where(Chunk.source_ref.startswith(prefix))).all()
        assert kept, prefix
        assert all(c.topic_id is None and c.concept_id is None for c in kept)
    assert _fts_ids(session, "zebraquant") and _fts_ids(session, "okapiturn")

    # Alias, edges and notes of the topic's concepts are gone; vault links of its notes too.
    assert session.exec(select(ConceptAlias)).all() == []
    concept_ids = owned_before[Concept.__table__]
    assert session.exec(select(ConceptEdge).where(
        ConceptEdge.src_concept_id.in_(concept_ids)
        | ConceptEdge.dst_concept_id.in_(concept_ids))).all() == []
    assert session.exec(select(ConceptNote).where(
        ConceptNote.concept_id.in_(concept_ids))).all() == []
    assert session.exec(select(ChunkConcept).where(
        ChunkConcept.concept_id.in_(concept_ids))).all() == []
    assert session.exec(select(VaultLink).where(VaultLink.src_ref == data.note_ref)).all() == []
    # Nothing on disk is touched.
    assert data.note_path.read_text().startswith("# Priors")

    # Cost history is kept.
    assert len(session.exec(select(LLMUsage)).all()) == 1

    # The other topic is whole.
    control = session.get(Topic, data.control.id)
    assert control is not None and _concepts(session, control.id)
    assert session.exec(select(Conversation)).all()
    assert session.exec(select(Message)).all()


def test_delete_topic_removes_a_fully_populated_topic(vec_session, tmp_path):
    session = vec_session
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    data = Populated(session, tmp_path, retriever)
    tid = data.tid
    control_owned = {t.name: ids for t, ids in owned_rows(session, data.control.id).items()}
    owned_before = owned_rows(session, tid)
    concept_ids = owned_before[Concept.__table__]
    chunk_ids = {c.id for c in session.exec(select(Chunk).where(
        (Chunk.topic_id == tid) | Chunk.concept_id.in_(concept_ids))).all()}
    removed_chunk_ids = {c.id for c in session.exec(select(Chunk).where(
        Chunk.id.in_(chunk_ids)
        & ~Chunk.source_ref.startswith("paperprobe:")
        & ~Chunk.source_ref.startswith("roleplayturn:"))).all()}
    vec_before = _vec_ids(session)
    assert removed_chunk_ids and removed_chunk_ids <= vec_before  # really embedded
    assert _fts_ids(session, "wombatword") and _fts_ids(session, "quokkanote")

    assert delete_topic(session, tid) is True

    _assert_deleted(session, data, owned_before, removed_chunk_ids)
    # No vector is left for a deleted chunk, and every surviving chunk keeps its vector.
    vec_after = _vec_ids(session)
    assert vec_after & removed_chunk_ids == set()
    chunk_ids_now = {c.id for c in session.exec(select(Chunk)).all()}
    assert vec_after == chunk_ids_now == vec_before - removed_chunk_ids
    # The other topic's rows are all still there, except the edge it shared with this one.
    for name, ids in control_owned.items():
        table = SQLModel.metadata.tables[name]
        ids = ids - owned_before.get(table, set())
        assert len(session.execute(select(table.c.id).where(table.c.id.in_(ids))).all()) \
            == len(ids), name

    assert delete_topic(session, tid) is False


def test_delete_topic_without_sqlite_vec(session, tmp_path):
    """The plain install (no memory extra): same cascade, FTS only."""
    data = Populated(session, tmp_path, None)
    tid = data.tid
    owned_before = owned_rows(session, tid)
    chunk_ids = {c.id for c in session.exec(
        select(Chunk).where(Chunk.topic_id == tid, ~Chunk.source_ref.startswith("paperprobe:"),
                            ~Chunk.source_ref.startswith("roleplayturn:"))).all()}
    assert delete_topic(session, tid) is True
    _assert_deleted(session, data, owned_before, chunk_ids)


def test_a_topic_that_research_left_half_made_can_be_deleted(session):
    """The walkthrough's case: a topic whose research failed has only a title and intent."""
    from adaptive_academy.models import TopicIntent

    first = Topic(title="Bayesian A/B testing")
    second = Topic(title="Bayesian A/B testing")
    session.add_all([first, second])
    session.commit()
    session.add(TopicIntent(topic_id=first.id, goal="g"))
    session.add(AgentEvent(topic_id=first.id, kind="research:error", detail="boom"))
    session.commit()
    assert delete_topic(session, first.id) is True
    session.expire_all()
    assert [t.id for t in session.exec(select(Topic)).all()] == [second.id]
    assert session.exec(select(AgentEvent)).all() == []


def test_delete_topic_refuses_while_its_research_runs(session):
    topic = Topic(title="Running")
    session.add(topic)
    session.commit()
    from adaptive_academy.engine.runlock import RunInProgress

    with exclusive_run(f"research:{topic.id}"):
        with pytest.raises(RunInProgress):
            delete_topic(session, topic.id)
    assert session.get(Topic, topic.id) is not None
    assert delete_topic(session, topic.id) is True


def test_remove_demo_goes_through_the_same_path(vec_session):
    """The demo's removal is delete_topic: chunks, FTS and vectors of the demo go too."""
    session = vec_session
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    keep = _real_topic(session, "Mine")
    keep_chunks = {c.id for c in session.exec(select(Chunk)).all()}
    demo = build_demo(session, now=NOW)
    retriever.on_index(session, [c.id for c in session.exec(select(Chunk)).all()])
    session.commit()
    demo_chunks = {c.id for c in session.exec(
        select(Chunk).where(Chunk.topic_id == demo.id)).all()}
    assert demo_chunks and demo_chunks <= _vec_ids(session)

    assert remove_demo(session, demo.id) is True
    session.expire_all()
    assert {c.id for c in session.exec(select(Chunk)).all()} == keep_chunks
    assert _vec_ids(session) == keep_chunks
    session.execute(text("INSERT INTO chunk_fts(chunk_fts, rank) VALUES('integrity-check', 1)"))
    assert session.get(Topic, keep.id) is not None
    # remove_demo still refuses a topic that is not a demo.
    assert remove_demo(session, keep.id) is False


# --- API ------------------------------------------------------------------------------------


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_delete_route_removes_a_topic(client, session):
    tid = client.post("/api/topics", json={"title": "Mine", "goal": "g"}).json()["id"]
    other = client.post("/api/topics", json={"title": "Other", "goal": "g"}).json()["id"]
    r = client.delete(f"/api/topics/{tid}")
    assert r.status_code == 204, r.text
    assert r.content == b""
    assert client.get(f"/api/topics/{tid}").status_code == 404
    assert [t["id"] for t in client.get("/api/topics").json()] == [other]
    assert client.delete(f"/api/topics/{tid}").status_code == 404


def test_delete_route_unknown_topic_is_404(client):
    assert client.delete("/api/topics/9999").status_code == 404


def test_delete_route_removes_a_demo_topic_too(client, session):
    tid = client.post("/api/demo").json()["topic_id"]
    assert client.delete(f"/api/topics/{tid}").status_code == 204
    assert client.get("/api/topics").json() == []
    # The demo routes keep working for scripts.
    tid = client.post("/api/demo").json()["topic_id"]
    assert client.delete(f"/api/demo/{tid}").status_code == 204


def test_delete_route_is_409_while_research_runs(client, session):
    tid = client.post("/api/topics", json={"title": "Busy", "goal": "g"}).json()["id"]
    with exclusive_run(f"research:{tid}"):
        r = client.delete(f"/api/topics/{tid}")
    assert r.status_code == 409
    assert "still being researched" in r.json()["detail"]
    assert client.get(f"/api/topics/{tid}").status_code == 200


def _topic_with_concept(session: Session) -> tuple[int, int]:
    topic = Topic(title="Sync")
    session.add(topic)
    session.flush()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="priors")
    session.add(concept)
    session.commit()
    return topic.id, concept.id


def test_delete_topic_clears_its_notes_sync_problems(session):
    from adaptive_academy.engine.notebook_sync import NOTEBOOK_SYNC

    tid, cid = _topic_with_concept(session)
    _other_tid, other_cid = _topic_with_concept(session)
    NOTEBOOK_SYNC.reset()
    try:
        NOTEBOOK_SYNC.record_problem(cid, "Couldn't update priors.md: locked")
        NOTEBOOK_SYNC.record_problem(other_cid, "Couldn't update priors.md: locked")
        NOTEBOOK_SYNC.record_problem("vault_path", "Couldn't sync to the vault: gone")
        before = NOTEBOOK_SYNC.status()
        assert (before["problems"], before["skipped_notes"]) == (3, 2)

        assert delete_topic(session, tid) is True

        after = NOTEBOOK_SYNC.status()
        assert (after["problems"], after["skipped_notes"]) == (2, 1)
    finally:
        NOTEBOOK_SYNC.reset()


def test_vault_status_reports_skipped_notes_apart_from_other_problems(client):
    from adaptive_academy.engine.notebook_sync import NOTEBOOK_SYNC

    NOTEBOOK_SYNC.reset()
    try:
        NOTEBOOK_SYNC.record_problem(7, "Couldn't update a.md: locked")
        NOTEBOOK_SYNC.record_problem("queue", "The vault sync queue is full")
        sync = client.get("/api/vault/status").json()["sync"]
        assert sync["problems"] == 2
        assert sync["skipped_notes"] == 1
    finally:
        NOTEBOOK_SYNC.reset()


def test_delete_topic_holds_the_write_lock_from_the_scan_to_the_delete(tmp_path, monkeypatch):
    """A background writer that commits a chunk for the topic after the scan would make the
    final delete(Topic) fail its foreign-key check; the lock taken first keeps it out."""
    import sqlite3

    from adaptive_academy import db
    from adaptive_academy.engine import topics

    path = str(tmp_path / "delete.db")
    engine = create_engine(f"sqlite:///{path}", connect_args=db.CONNECT_ARGS)

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    ensure_fts(engine)
    late_writes: list[str] = []
    real_owned_rows = topics.owned_rows

    def owned_rows_then_late_chunk(session, topic_id):
        owned = real_owned_rows(session, topic_id)
        conn = sqlite3.connect(path, timeout=0.2)
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            conn.execute(
                "INSERT INTO chunk(kind, topic_id, source_ref, ordinal, heading, text, context, "
                "content_hash, meta, created_at) VALUES ('source_doc', ?, 'sourcedoc:999', 0, "
                "'', 'late', '', 'h', '{}', '2026-01-01')", (topic_id,))
            conn.commit()
            late_writes.append("written")
        except sqlite3.OperationalError as exc:
            late_writes.append(f"blocked: {exc}")
        finally:
            conn.close()
        return owned

    monkeypatch.setattr(topics, "owned_rows", owned_rows_then_late_chunk)
    with Session(engine) as session:
        tid, _cid = _topic_with_concept(session)
        assert delete_topic(session, tid) is True
        assert session.get(Topic, tid) is None
        assert session.exec(select(Chunk)).all() == []
    assert late_writes == ["blocked: database is locked"]
    engine.dispose()
