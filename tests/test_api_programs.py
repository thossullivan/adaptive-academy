import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import Assessment, TopicIntent

SYNTH = {
    "milestones": [
        {"title": "Math foundations", "success_criteria": "derive backprop cold",
         "depends_on": [],
         "topics": [{"title": "Linear algebra for DL", "why": "prereq"}]},
        {"title": "Architectures", "success_criteria": "transformer unaided",
         "depends_on": [0],
         "topics": [{"title": "Attention from scratch", "why": "core"}]},
    ]
}


def _client(session: Session, llm_payloads: list[str] | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    payloads = llm_payloads or [json.dumps(SYNTH)]
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=p) for p in payloads])
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "phd_curricula": [RawSource(title="Quals", url="https://mit.edu/q", tier=1)],
    })
    return TestClient(app)


def _make_program(client) -> int:
    r = client.post("/api/programs", json={
        "title": "PhD prep", "goal_statement": "research-ready in custom LLMs",
        "focus_area": "custom LLMs", "prior_knowledge": "MS-level math",
        "weekly_time_budget": "10h", "horizon": "2 years", "target_depth": "phd"})
    assert r.status_code == 200
    return r.json()["id"]


def test_create_list_get_program(session):
    client = _client(session)
    pid = _make_program(client)
    assert client.get("/api/programs").json()[0]["title"] == "PhD prep"
    detail = client.get(f"/api/programs/{pid}").json()
    assert detail["program"]["id"] == pid
    assert detail["milestones"] == []
    assert client.get("/api/programs/999").status_code == 404


def test_research_accept_start_flow(session):
    client = _client(session)
    pid = _make_program(client)

    r = client.post(f"/api/programs/{pid}/research")
    assert r.status_code == 200
    detail = r.json()
    assert [m["title"] for m in detail["milestones"]] == ["Math foundations", "Architectures"]
    links = [link for m in detail["milestones"] for link in m["links"]]
    assert all(link["status"] == "proposed" for link in links)

    # second research run refused
    assert client.post(f"/api/programs/{pid}/research").status_code == 400

    # accept one, prune one
    r = client.post(f"/api/programs/{pid}/accept", json={
        "accepted_link_ids": [links[0]["id"]], "pruned_link_ids": [links[1]["id"]]})
    assert r.status_code == 200
    statuses = {link["id"]: link["status"]
                for m in r.json()["milestones"] for link in m["links"]}
    assert statuses[links[0]["id"]] == "stub"
    assert statuses[links[1]["id"]] == "pruned"

    # start the stub → creates Topic + prefilled intent, flips to started
    r = client.post(f"/api/programs/{pid}/links/{links[0]['id']}/start")
    assert r.status_code == 200
    topic_id = r.json()["topic_id"]
    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
    assert "research-ready in custom LLMs" in intent.goal
    assert intent.prior_knowledge == "MS-level math"

    # idempotent: starting again returns the same topic
    assert client.post(f"/api/programs/{pid}/links/{links[0]['id']}/start").json()["topic_id"] == topic_id
    # starting a pruned link is a 400
    assert client.post(f"/api/programs/{pid}/links/{links[1]['id']}/start").status_code == 400


def test_milestone_edit_and_override(session):
    client = _client(session)
    pid = _make_program(client)
    client.post(f"/api/programs/{pid}/research")
    mid = client.get(f"/api/programs/{pid}").json()["milestones"][0]["id"]

    r = client.put(f"/api/programs/{pid}/milestones/{mid}",
                   json={"title": "Math core", "success_criteria": "new bar"})
    assert r.status_code == 200
    assert r.json()["title"] == "Math core"

    assert client.post(f"/api/programs/{pid}/milestones/{mid}/override",
                       json={"reason": "  "}).status_code == 400
    r = client.post(f"/api/programs/{pid}/milestones/{mid}/override",
                    json={"reason": "moving on, verified offline"})
    assert r.status_code == 200
    assert r.json()["gate_status"] == "overridden"
    events = client.get(f"/api/programs/{pid}/events").json()
    assert any(e["kind"] == "program:gate_override" for e in events)


def test_gate_endpoint_and_program_context(session):
    client = _client(session)
    pid = _make_program(client)
    client.post(f"/api/programs/{pid}/research")
    detail = client.get(f"/api/programs/{pid}").json()
    mid = detail["milestones"][0]["id"]
    link_id = detail["milestones"][0]["links"][0]["id"]
    client.post(f"/api/programs/{pid}/accept", json={"accepted_link_ids": [link_id],
                                                     "pruned_link_ids": []})
    topic_id = client.post(f"/api/programs/{pid}/links/{link_id}/start").json()["topic_id"]

    # empty gate: no curriculum/concepts yet
    r = client.get(f"/api/programs/{pid}/milestones/{mid}/gate")
    assert r.status_code == 200
    assert r.json()["verdict"] == "open"
    assert "no evidence yet" in r.json()["reason"]

    # materialize a concept + evidence by hand (curriculum pipeline tested elsewhere)
    from adaptive_academy.models import Concept, KnowledgeEstimate, Track
    track = Track(topic_id=topic_id, title="T")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="Attention", is_load_bearing=True)
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id))
    t0 = datetime(2026, 7, 1)
    session.add(Assessment(concept_id=concept.id, kind="teach", prompt="p",
                           score=0.9, created_at=t0))
    session.add(Assessment(concept_id=concept.id, kind="recall", prompt="p",
                           score=0.85, created_at=t0 + timedelta(days=8)))
    session.commit()

    r = client.get(f"/api/programs/{pid}/milestones/{mid}/gate")
    assert r.json()["verdict"] == "passed"
    assert r.json()["concepts"][0]["verdict"] == "verified"

    ctx = client.get(f"/api/topics/{topic_id}/program-context")
    assert ctx.status_code == 200
    assert ctx.json()["milestone_id"] == mid
    assert ctx.json()["gate_status"] == "passed"
    assert ctx.json()["unverified"] == []

    # a topic outside any program has no context
    lone = client.post("/api/topics", json={"title": "lone", "goal": "g"}).json()["id"]
    assert client.get(f"/api/topics/{lone}/program-context").status_code == 404


def test_curriculum_import_survives_program_aliases(session):
    """Regression (finding 1): a program topic's curriculum generation registers a
    ConceptAlias row per concept (apply_program_aliases). Re-importing markdown deletes
    and recreates the topic's Track/Concepts — under foreign_keys=ON that used to raise
    IntegrityError because the old ConceptAlias rows were never deleted first."""
    from adaptive_academy.models import Concept, ConceptAlias, Track

    curriculum_payload = {
        "overview": "o",
        "phases": [
            {"title": "P1", "items": [{"type": "build", "text": "implement backprop",
                                       "concept_refs": ["Backprop"]}],
             "deliverable": {"kind": "repo", "text": "backprop from scratch"}},
        ],
    }
    foundation_payload = {"overview": "o", "key_concepts": ["Backprop"],
                          "prerequisite_map": {}}
    synth_payload = {"milestones": [
        {"title": "Foundations", "success_criteria": "derive backprop cold",
         "depends_on": [], "topics": [{"title": "Backprop", "why": "core"}]},
    ]}

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    llm = ScriptedLLMClient([
        LLMResponse(text=json.dumps(synth_payload)),
        LLMResponse(text=json.dumps(foundation_payload)),
        LLMResponse(text=json.dumps(curriculum_payload)),
    ])
    app.dependency_overrides[get_llm] = lambda: llm
    src = [RawSource(title="s", url="https://e.com/1", tier=1, relevance=0.9, summary="s")]
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "phd_curricula": list(src), "foundational_papers": list(src),
    })
    client = TestClient(app)

    pid = client.post("/api/programs", json={
        "title": "PhD prep", "goal_statement": "research-ready",
        "focus_area": "custom LLMs"}).json()["id"]
    client.post(f"/api/programs/{pid}/research")
    detail = client.get(f"/api/programs/{pid}").json()
    link_id = detail["milestones"][0]["links"][0]["id"]
    client.post(f"/api/programs/{pid}/accept",
                json={"accepted_link_ids": [link_id], "pruned_link_ids": []})
    topic_id = client.post(f"/api/programs/{pid}/links/{link_id}/start").json()["topic_id"]

    assert client.post(f"/api/topics/{topic_id}/research").status_code == 200
    proposed = client.get(f"/api/topics/{topic_id}/sources?status=proposed").json()
    client.post(f"/api/topics/{topic_id}/sources/review",
                json={"accepted_ids": [s["id"] for s in proposed], "pruned_ids": []})
    assert client.post(f"/api/topics/{topic_id}/curriculum").status_code == 200

    # Curriculum generation on a program topic registered a ConceptAlias per concept.
    old_concepts = session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)
    ).all()
    assert old_concepts  # sanity: the pipeline actually produced concepts
    old_concept_ids = [c.id for c in old_concepts]
    assert session.exec(
        select(ConceptAlias).where(ConceptAlias.concept_id.in_(old_concept_ids))
    ).all()

    md = "# Backprop\n\n## Phase 1 — Rebuilt\n- [ ] (read) reread the paper\n"
    r = client.post(f"/api/topics/{topic_id}/curriculum/import", json={"markdown": md})
    assert r.status_code == 200

    # Old concepts (and their aliases) are gone; no IntegrityError was raised.
    assert session.exec(
        select(ConceptAlias).where(ConceptAlias.concept_id.in_(old_concept_ids))
    ).all() == []
    assert session.exec(select(Concept).where(Concept.id.in_(old_concept_ids))).all() == []


def test_program_context_orphaned_link_is_404(session):
    """A link whose milestone row is missing must 404, not 500. This state can't arise
    through normal ORM writes under foreign_keys=ON (milestone_id is FK-protected), but
    the defensive check still earns its keep against out-of-band data — toggle the
    pragma off just long enough to construct the orphaned fixture row."""
    from sqlalchemy import text

    from adaptive_academy.models import ProgramTopicLink

    client = _client(session)
    tid = client.post("/api/topics", json={"title": "orphan", "goal": "g"}).json()["id"]
    session.execute(text("PRAGMA foreign_keys=OFF"))
    session.add(ProgramTopicLink(milestone_id=999, topic_id=tid, status="started",
                                 proposed_title="orphan"))
    session.commit()
    session.execute(text("PRAGMA foreign_keys=ON"))
    assert client.get(f"/api/topics/{tid}/program-context").status_code == 404
