"""The demo topic: a deterministic, LLM-free topic shaped like a few weeks of real use, and the
POST/DELETE /api/demo endpoints that add and remove it in one click (no API key needed)."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from adaptive_academy.api import deps as api_deps
from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.demo import DEMO_TITLE, build_demo, ensure_demo, find_demo, remove_demo
from adaptive_academy.engine import graph
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Chunk,
    Concept,
    ConceptEdge,
    Conversation,
    Deliverable,
    Item,
    KnowledgeEstimate,
    Message,
    Phase,
    RecallPrompt,
    ReferenceAnchor,
    Rubric,
    Sidebar,
    SourceDoc,
    SRSCard,
    Topic,
    TopicFoundation,
    TopicIntent,
    Track,
)
from adaptive_academy.prompts import ASSESS_ARTIFACT, GRADE, PF_CONSOLIDATE, TEACH

NOW =datetime(2026, 10, 19, 15, 30, 0)


def _rows(session: Session, model) -> list:
    return list(session.exec(select(model)).all())


def _table_counts(session: Session) -> dict[str, int]:
    """Row count of every table in the database (FTS shadow segment tables excluded: their
    b-tree segments keep tombstones after a delete, so their row count is not a row count)."""
    names = [
        r[0]
        for r in session.exec(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ).all()
    ]
    skip = {"chunk_fts_data", "chunk_fts_idx", "chunk_fts_config"}
    return {
        n: session.exec(text(f'SELECT count(*) FROM "{n}"')).one()[0]
        for n in names
        if n not in skip
    }


# --- builder --------------------------------------------------------------------------------


def test_build_demo_marks_and_titles_the_topic_as_a_demo(session):
    topic = build_demo(session, now=NOW)
    assert topic.is_demo is True
    assert topic.title == DEMO_TITLE
    assert "(demo)" in topic.title
    assert find_demo(session).id == topic.id


def test_build_demo_has_data_for_every_page(session):
    topic = build_demo(session, now=NOW)
    tid = topic.id

    # Sources page: an intent, a foundation, and an accepted reading list.
    assert len(_rows(session, TopicIntent)) == 1
    foundation = session.exec(select(TopicFoundation)).one()
    assert foundation.overview and foundation.key_concepts and foundation.prerequisite_map
    sources = _rows(session, SourceDoc)
    assert len([s for s in sources if s.status == "accepted"]) >= 6
    assert all(s.topic_id == tid for s in sources)

    # Track / Today / Wayfinder: a phased track with some steps done, some not.
    track = session.exec(select(Track)).one()
    phases = _rows(session, Phase)
    items = _rows(session, Item)
    assert len(phases) == 4
    statuses = {i.status for i in items}
    assert statuses == {"todo", "doing", "done"}
    assert len(items) >= 14
    done_by_phase = {
        p.id: [i.status for i in items if i.phase_id == p.id] for p in phases
    }
    assert any(all(s == "done" for s in v) for v in done_by_phase.values())  # a phase complete
    assert any(all(s == "todo" for s in v) for v in done_by_phase.values())  # a phase ahead
    deliverables = _rows(session, Deliverable)
    assert len(deliverables) == 4
    assert any(d.artifact_url and d.review_verdict for d in deliverables)  # one shipped
    assert len([s for s in _rows(session, Sidebar) if s.track_id == track.id]) >= 2

    # Constellation: concepts with prerequisite edges, some load-bearing, all estimated.
    concepts = _rows(session, Concept)
    assert len(concepts) >= 12
    assert any(c.is_load_bearing for c in concepts)
    assert any(not c.is_load_bearing for c in concepts)
    assert len(_rows(session, KnowledgeEstimate)) == len(concepts)
    edges = _rows(session, ConceptEdge)
    assert len(edges) >= 12
    assert all(e.kind == "prerequisite" and e.valid_until is None for e in edges)

    # The Assessment spine: several kinds over ~3 weeks, the latest recent.
    assessments = _rows(session, Assessment)
    assert len(assessments) >= 15
    kinds = {a.kind for a in assessments}
    assert {
        "self_explanation", "calibration", "recall", "teach", "artifact_review",
        "productive_failure", "source_quiz",
    } <= kinds
    stamps = sorted(a.created_at for a in assessments)
    assert NOW - stamps[0] >= timedelta(days=18)
    assert NOW - stamps[-1] <= timedelta(days=2)
    # Inserted in time order, so id order (what the dashboard trend uses) is chronological.
    by_id = sorted(assessments, key=lambda a: a.id)
    assert [a.created_at for a in by_id] == stamps
    assert any(a.delta is not None and a.baseline_assessment_id for a in assessments)
    assert any(a.confidence_predicted is not None for a in assessments)
    assert _rows(session, Rubric) and _rows(session, ReferenceAnchor)
    # Each row carries the current tag of the prompt that grades its kind, as the real writers
    # would, and that tag is in the demo's own trace.
    grading_prompt = {"teach": TEACH, "productive_failure": PF_CONSOLIDATE,
                      "artifact_review": ASSESS_ARTIFACT}
    for a in assessments:
        assert a.prompt_tag == grading_prompt.get(a.kind, GRADE).tag, a.kind
    traced = {e.detail for e in _rows(session, AgentEvent) if e.kind == "prompt"}
    assert {a.prompt_tag for a in assessments} <= traced

    # Tutor: conversations where the learner logged an attempt (they feed the trace and the
    # memory index).
    convos = _rows(session, Conversation)
    assert len(convos) == 2
    assert all(c.attempt_logged and c.topic_id == tid for c in convos)
    assert len(_rows(session, Message)) >= 8

    # Trace: topic-level and conversation-level agent events.
    events = _rows(session, AgentEvent)
    assert len([e for e in events if e.topic_id == tid]) >= 15
    assert {c.id for c in convos} <= {e.conversation_id for e in events}

    # Retention: cards due now, proposed cards, and decay checks due.
    cards = _rows(session, SRSCard)
    assert any(c.status == "active" and c.due_at <= NOW for c in cards)
    assert any(c.status == "proposed" for c in cards)
    prompts = _rows(session, RecallPrompt)
    assert any(p.status == "active" and p.due_at <= NOW for p in prompts)
    assert any(p.status == "active" and p.due_at > NOW for p in prompts)

    # Memory index: the learner record is searchable.
    assert len([c for c in _rows(session, Chunk) if c.topic_id == tid]) >= 10


def test_build_demo_is_deterministic(session):
    from sqlmodel import SQLModel, create_engine
    from sqlmodel.pool import StaticPool

    from adaptive_academy.db import ensure_fts

    def snapshot(s: Session) -> dict:
        return {
            "items": [(i.text, i.status, i.type) for i in s.exec(select(Item).order_by(Item.id))],
            "assessments": [
                (a.kind, a.score, a.created_at, a.delta, a.confidence_predicted)
                for a in s.exec(select(Assessment).order_by(Assessment.id))
            ],
            "edges": sorted(
                (e.src_concept_id, e.dst_concept_id) for e in s.exec(select(ConceptEdge))
            ),
            "events": [(e.kind, e.detail, e.created_at) for e in s.exec(select(AgentEvent))],
            "cards": [(c.front, c.due_at, c.status) for c in s.exec(select(SRSCard))],
        }

    build_demo(session, now=NOW)
    other = create_engine("sqlite://", connect_args={"check_same_thread": False},
                          poolclass=StaticPool)
    SQLModel.metadata.create_all(other)
    ensure_fts(other)
    with Session(other) as s2:
        build_demo(s2, now=NOW)
        assert snapshot(s2) == snapshot(session)


def test_demo_rubric_terms_and_anchor_key_points_are_plain_words():
    # The anchor checks leave formula-like terms to the grader (assess.is_formula_like), so a
    # demo rubric term, anchor key point, or seeded "omitted required element" gap that is a
    # formula would show data the app can never produce.
    from adaptive_academy import demo
    from adaptive_academy.engine.assess import is_formula_like

    terms = [t for ts in demo.RUBRIC_TERMS.values() for t in ts]
    terms += [p for *_, points in demo.ANCHORS for p in points]
    omitted = [g.split(": ", 1)[1] for p in demo.PROBES for g in p.gaps
               if g.startswith("omitted required element: ")]
    assert not [t for t in terms + omitted if is_formula_like(t)]


def test_demo_attention_probes_have_the_rule_gaps_the_matcher_gives():
    from adaptive_academy import demo
    from adaptive_academy.engine.assess import apply_rules_checks

    for p in demo.PROBES:
        if p.concept == "attn" and p.kind in ("self_explanation", "calibration"):
            seeded = [g for g in p.gaps if g.startswith("omitted required element")]
            assert apply_rules_checks(p.response, demo.RUBRIC_TERMS["attn"], []) == seeded


def test_startup_graph_backfill_leaves_demo_edges_alone(session):
    build_demo(session, now=NOW)
    before = sorted((e.id, e.src_concept_id, e.dst_concept_id, e.valid_until)
                    for e in _rows(session, ConceptEdge))
    graph.backfill(session)
    session.commit()
    after = sorted((e.id, e.src_concept_id, e.dst_concept_id, e.valid_until)
                   for e in _rows(session, ConceptEdge))
    assert after == before


def test_ensure_demo_is_idempotent(session):
    first, created = ensure_demo(session, now=NOW)
    second, created_again = ensure_demo(session, now=NOW)
    assert created is True and created_again is False
    assert first.id == second.id
    assert len(_rows(session, Topic)) == 1


def test_remove_demo_leaves_other_topics_untouched(session):
    real = Topic(title="My own topic")
    session.add(real)
    session.commit()
    session.add(Track(topic_id=real.id, title="Core"))
    session.commit()
    before = _table_counts(session)

    build_demo(session, now=NOW)
    assert remove_demo(session) is True
    assert _table_counts(session) == before
    assert session.get(Topic, real.id) is not None
    assert remove_demo(session) is False


# --- API ------------------------------------------------------------------------------------


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def no_llm(monkeypatch):
    """No key, and fail loudly if anything builds a real (or any) LLM client."""

    class _NoNetwork:
        def __init__(self, *a, **kw):
            raise AssertionError("a real Anthropic client was constructed")

    def _forbidden():
        raise AssertionError("an LLM-backed dependency was resolved")

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setattr("adaptive_academy.llm.anthropic_client.Anthropic", _NoNetwork)
    monkeypatch.setattr("adaptive_academy.llm.anthropic_researcher.Anthropic", _NoNetwork)
    for dep in (api_deps.get_llm, api_deps.get_researcher, api_deps.get_anchor_client):
        app.dependency_overrides[dep] = _forbidden


def test_post_demo_creates_it_without_a_key(client, session, no_llm):
    r = client.post("/api/demo")
    assert r.status_code == 200, r.text
    tid = r.json()["topic_id"]
    assert r.json()["created"] is True
    topic = client.get(f"/api/topics/{tid}").json()
    assert topic["is_demo"] is True
    assert topic["title"] == DEMO_TITLE
    listed = {t["id"]: t["is_demo"] for t in client.get("/api/topics").json()}
    assert listed == {tid: True}


def test_post_demo_is_idempotent(client, session, no_llm):
    first = client.post("/api/demo").json()
    second = client.post("/api/demo").json()
    assert second == {"topic_id": first["topic_id"], "created": False}
    assert len(_rows(session, Topic)) == 1


def test_regular_topics_are_not_demos(client, session):
    tid = client.post("/api/topics", json={"title": "Mine", "goal": "g"}).json()["id"]
    assert client.get(f"/api/topics/{tid}").json()["is_demo"] is False


def test_delete_demo_removes_every_row(client, session, no_llm):
    # A real topic with its own rows must survive; the demo must leave nothing behind.
    real = client.post("/api/topics", json={"title": "Mine", "goal": "g"}).json()["id"]
    track = Track(topic_id=real, title="Core")
    session.add(track)
    session.commit()
    session.add(Concept(track_id=track.id, name="Eigenvectors"))
    session.commit()
    before = _table_counts(session)

    tid = client.post("/api/demo").json()["topic_id"]
    # Visiting demo pages writes rows too (a tutor visit starts a conversation).
    concept_id = client.get(f"/api/topics/{tid}").json()["concepts"][0]["id"]
    assert client.post("/api/conversations", json={"topic_id": tid,
                                                   "concept_id": concept_id}).status_code == 200
    assert _table_counts(session) != before

    r = client.delete(f"/api/demo/{tid}")
    assert r.status_code == 204
    assert _table_counts(session) == before
    assert client.get(f"/api/topics/{tid}").status_code == 404
    assert [t["id"] for t in client.get("/api/topics").json()] == [real]


def test_delete_demo_when_absent_is_404(client, session, no_llm):
    assert client.delete("/api/demo").status_code == 404
    assert client.delete("/api/demo/12345").status_code == 404


def test_delete_demo_refuses_a_topic_that_is_not_the_demo(client, session, no_llm):
    real = client.post("/api/topics", json={"title": "Mine", "goal": "g"}).json()["id"]
    client.post("/api/demo")
    before = _table_counts(session)

    r = client.delete(f"/api/demo/{real}")

    assert r.status_code == 400
    assert "not a demo" in r.json()["detail"]
    assert _table_counts(session) == before


def test_delete_demo_by_id_removes_only_the_named_demo(client, session, no_llm):
    # Two demos can exist (a race, or an older database); Remove on one demo's dashboard must
    # delete that demo, not whichever is oldest.
    first = build_demo(session, now=NOW)
    before = _table_counts(session)
    second = build_demo(session, now=NOW)
    assert first.id < second.id

    assert client.delete(f"/api/demo/{second.id}").status_code == 204

    assert _table_counts(session) == before
    assert session.get(Topic, first.id) is not None
    assert [t["id"] for t in client.get("/api/topics").json()] == [first.id]


def test_delete_demo_without_an_id_still_removes_the_demo(client, session, no_llm):
    # The id-less form stays for scripts (e2e cleanup, `just seed`'s hint).
    tid = client.post("/api/demo").json()["topic_id"]
    assert client.delete("/api/demo").status_code == 204
    assert client.get(f"/api/topics/{tid}").status_code == 404


def test_demo_pages_read_without_a_key(client, session, no_llm):
    """Every read the demo's pages make answers from stored rows — no key, no model call."""
    tid = client.post("/api/demo").json()["topic_id"]
    topic = client.get(f"/api/topics/{tid}").json()
    assert topic["intent"]["goal"] and topic["has_foundation"] and topic["has_track"]

    cur = client.get(f"/api/topics/{tid}/curriculum").json()
    assert len(cur["phases"]) == 4 and cur["concepts"]
    assert client.get(f"/api/topics/{tid}/foundation").status_code == 200
    assert len(client.get(f"/api/topics/{tid}/sources?status=accepted").json()) >= 6
    assert len(client.get(f"/api/topics/{tid}/events").json()) >= 15

    g = client.get(f"/api/topics/{tid}/graph").json()
    assert g["nodes"] and g["edges"]

    wind = client.get(f"/api/topics/{tid}/wind").json()
    assert wind["state"] in {"steady", "cruising"}
    fleet = client.get("/api/fleet").json()
    assert [w["topic_id"] for w in fleet] == [tid]

    assert client.get(f"/api/topics/{tid}/retention?due=true").json()["cards"]
    assert client.get(f"/api/topics/{tid}/decay").json()["items"]

    # The competence grade is the stored estimate, on the newest row only.
    grades = {}
    for c in topic["concepts"]:
        rows = client.get(f"/api/concepts/{c['id']}/assessments").json()
        assert all(a["estimate_level"] is None for a in rows[1:])
        if rows:
            stored = session.exec(select(KnowledgeEstimate).where(
                KnowledgeEstimate.concept_id == c["id"])).one()
            assert rows[0]["estimate_level"] == stored.level
            grades[c["name"]] = stored.level
    assert grades["Chain Rule and Computational Graphs"] == "high"
    assert grades["Token Embeddings"] == "medium"
    # A productive-failure attempt came last but never writes the estimate.
    assert grades["Causal Self-Attention"] == "low"

    facts = client.get(f"/api/topics/{tid}/story/facts").json()
    assert facts["assessments_count"] >= 15
    assert facts["items_done"] > 0 and facts["phases_completed"] >= 1
    assert facts["shipped"]

    stats = client.get(f"/api/memory/stats?topic_id={tid}").json()
    assert sum(stats["by_kind"].values()) >= 10


def test_a_new_tutor_session_on_a_demo_concept_starts_locked(client, session, no_llm):
    """The demo's logged attempt belongs to its own conversation: a new session on the same
    concept starts with no attempt, so the reveal gate is closed again."""
    tid = client.post("/api/demo").json()["topic_id"]
    causal = session.exec(select(Concept).where(Concept.name == "Causal Self-Attention")).one()
    logged = session.exec(select(Conversation).where(Conversation.concept_id == causal.id)).one()
    assert logged.attempt_logged
    fresh = client.post("/api/conversations",
                        json={"topic_id": tid, "concept_id": causal.id}).json()
    assert fresh["id"] != logged.id
    assert fresh["attempt_logged"] is False and fresh["messages"] == []
