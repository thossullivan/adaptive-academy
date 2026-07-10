"""Program-layer loop: intake → research → accept → start topic → curriculum with
alias carryover → evidence rows → gate verdict flips. Scripted LLM/researcher doubles;
LLM responses are queued IN CALL ORDER: program synthesis, topic foundation, topic
curriculum (×2 topics)."""
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
from adaptive_academy.models import Assessment, Concept, KnowledgeEstimate, Track

SYNTH = {"milestones": [
    {"title": "Foundations", "success_criteria": "derive backprop cold", "depends_on": [],
     "topics": [{"title": "Backprop", "why": "core"}]},
    {"title": "Architectures", "success_criteria": "transformer unaided", "depends_on": [0],
     "topics": [{"title": "Transformers", "why": "core"}]},
]}
FOUNDATION_1 = {"overview": "o", "key_concepts": ["Backprop", "Chain rule"],
                "prerequisite_map": {"Backprop": ["Chain rule"]}}
CURRICULUM_1 = {"overview": "o", "phases": [
    {"title": "P1", "items": [{"type": "build", "text": "implement backprop",
                               "concept_refs": ["Backprop"]}],
     "deliverable": {"kind": "repo", "text": "backprop from scratch"}},
    {"title": "P2", "items": [{"type": "write", "text": "explain chain rule",
                               "concept_refs": ["Chain rule"]}],
     "deliverable": {"kind": "blog", "text": "chain rule post"}},
]}
FOUNDATION_2 = {"overview": "o", "key_concepts": ["Attention", "Chain rule"],
                "prerequisite_map": {"Attention": ["Chain rule"]}}
CURRICULUM_2 = {"overview": "o", "phases": [
    {"title": "P1", "items": [{"type": "build", "text": "implement attention",
                               "concept_refs": ["Attention"]}],
     "deliverable": {"kind": "repo", "text": "attention from scratch"}},
    {"title": "P2", "items": [{"type": "write", "text": "revisit chain rule",
                               "concept_refs": ["Chain rule"]}],
     "deliverable": {"kind": "blog", "text": "post"}},
]}


def _client(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    llm = ScriptedLLMClient([
        LLMResponse(text=json.dumps(SYNTH)),
        LLMResponse(text=json.dumps(FOUNDATION_1)),
        LLMResponse(text=json.dumps(CURRICULUM_1)),
        LLMResponse(text=json.dumps(FOUNDATION_2)),
        LLMResponse(text=json.dumps(CURRICULUM_2)),
    ])
    app.dependency_overrides[get_llm] = lambda: llm
    src = [RawSource(title="s", url="https://e.com/1", tier=1, relevance=0.9, summary="s")]
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "phd_curricula": list(src), "foundational_papers": list(src),
    })
    return TestClient(app)


def _run_topic_pipeline(client, topic_id: int) -> None:
    assert client.post(f"/api/topics/{topic_id}/research").status_code == 200
    proposed = client.get(f"/api/topics/{topic_id}/sources?status=proposed").json()
    client.post(f"/api/topics/{topic_id}/sources/review",
                json={"accepted_ids": [s["id"] for s in proposed], "pruned_ids": []})
    assert client.post(f"/api/topics/{topic_id}/curriculum").status_code == 200


def test_program_loop_end_to_end(session):
    client = _client(session)
    pid = client.post("/api/programs", json={
        "title": "PhD prep", "goal_statement": "research-ready",
        "focus_area": "custom LLMs"}).json()["id"]
    client.post(f"/api/programs/{pid}/research")
    detail = client.get(f"/api/programs/{pid}").json()
    m1, m2 = detail["milestones"]
    all_links = [link for m in detail["milestones"] for link in m["links"]]
    client.post(f"/api/programs/{pid}/accept",
                json={"accepted_link_ids": [link["id"] for link in all_links], "pruned_link_ids": []})

    # ---- start topic 1, run its pipeline (foundation+curriculum use scripted LLM) ----
    t1 = client.post(f"/api/programs/{pid}/links/{m1['links'][0]['id']}/start").json()["topic_id"]
    _run_topic_pipeline(client, t1)

    # gate 1 open — load-bearing "Chain rule" has no evidence yet
    gate = client.get(f"/api/programs/{pid}/milestones/{m1['id']}/gate").json()
    assert gate["verdict"] == "open"
    names = {c["name"]: c["verdict"] for c in gate["concepts"]}
    assert names == {"Chain rule": "never_probed_cold"}

    # ---- inject evidence: artifact grade + delayed held recall ----
    chain1 = session.exec(
        select(Concept).join(Track).where(Track.topic_id == t1, Concept.name == "Chain rule")
    ).first()
    est = session.exec(select(KnowledgeEstimate)
                       .where(KnowledgeEstimate.concept_id == chain1.id)).first()
    est.level = "medium"  # learner actually knows it moderately
    session.add(est)
    t0 = datetime(2026, 7, 1)
    session.add(Assessment(concept_id=chain1.id, kind="teach", prompt="p", score=0.9,
                           created_at=t0))
    session.add(Assessment(concept_id=chain1.id, kind="recall", prompt="p", score=0.85,
                           created_at=t0 + timedelta(days=8)))
    session.commit()
    assert client.get(f"/api/programs/{pid}/milestones/{m1['id']}/gate").json()["verdict"] == "passed"

    # ---- start topic 2: alias carryover seeds "Chain rule" from topic 1 ----
    t2 = client.post(f"/api/programs/{pid}/links/{m2['links'][0]['id']}/start").json()["topic_id"]
    _run_topic_pipeline(client, t2)
    chain2 = session.exec(
        select(Concept).join(Track).where(Track.topic_id == t2, Concept.name == "Chain rule")
    ).first()
    est2 = session.exec(select(KnowledgeEstimate)
                        .where(KnowledgeEstimate.concept_id == chain2.id)).first()
    assert est2.level == "medium"  # seeded from topic 1, not the cold "high" default

    # gate 2 still open: carryover seeds the ESTIMATE, but gate evidence is per concept
    # row — topic 2's "Chain rule" has no assessments of its own yet (the honest reading)
    gate2 = client.get(f"/api/programs/{pid}/milestones/{m2['id']}/gate").json()
    assert gate2["verdict"] == "open"

    # program context for topic 2 names its milestone
    ctx = client.get(f"/api/topics/{t2}/program-context").json()
    assert ctx["milestone_title"] == "Architectures"
