"""End-to-end revision loop (spec §7): seed a program with one passed leg →
revise (scripted researcher + LLM) → accept an add_topic and a prune_topic,
reject a revise_milestone → the map reflects exactly the accepted changes and
the nudge clears."""
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.engine.gates import milestone_gate
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, KnowledgeEstimate, Milestone, Program, ProgramIntent,
    ProgramTopicLink, Topic, Track,
)

T0 = datetime(2026, 7, 1)


def _seed(session):
    """Program with leg1 (started topic, verified evidence → passes) + leg2 (stubs)."""
    p = Program(title="PhD prep", goal_statement="research-ready")
    session.add(p)
    session.commit()
    session.add(ProgramIntent(program_id=p.id, focus_area="custom LLMs"))
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0)
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    session.add(m1)
    session.add(m2)
    topic = Topic(title="Backprop")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Backprop")
    session.add(track)
    session.commit()
    c = Concept(track_id=track.id, name="Chain rule", is_load_bearing=True)
    session.add(c)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=c.id))
    session.add(Assessment(concept_id=c.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=c.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.add(ProgramTopicLink(milestone_id=m1.id, topic_id=topic.id, status="started"))
    stub = ProgramTopicLink(milestone_id=m2.id, proposed_title="Old attention survey",
                            status="stub")
    session.add(stub)
    session.commit()
    milestone_gate(session, m1)  # flips to passed, emits program:gate_passed
    return p, m1, m2, stub


def _client(session: Session, synth: dict) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps(synth))])
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "whats_new": [RawSource(title="MoE", url="https://e.com/moe", tier=1,
                                summary="mixture of experts everywhere")],
        "frontier_shifts": [RawSource(title="SSMs", url="https://e.com/ssm", tier=1)],
    })
    return TestClient(app)


def test_revision_loop_end_to_end(session):
    p, m1, m2, stub = _seed(session)
    synth = {"map_health": "leg 2 predates the MoE/SSM shift",
             "changes": [
                 {"kind": "add_topic",
                  "payload": {"milestone_id": m2.id, "title": "MoE routing"},
                  "why": "field moved", "source_urls": ["https://e.com/moe"]},
                 {"kind": "prune_topic", "payload": {"link_id": stub.id},
                  "why": "superseded", "source_urls": []},
                 {"kind": "revise_milestone",
                  "payload": {"milestone_id": m2.id, "title": "Architectures v2"},
                  "why": "broaden", "source_urls": []},
             ]}
    client = _client(session, synth)

    # nudge is on (gate passed, never revised)
    assert client.get(f"/api/programs/{p.id}").json()["revision_suggested"] is True

    rev = client.post(f"/api/programs/{p.id}/revise").json()
    assert len(rev["changes"]) == 3  # all valid (m2 unstarted, stub prunable)
    by_kind = {c["kind"]: c["id"] for c in rev["changes"]}

    client.post(f"/api/programs/{p.id}/changes/{by_kind['add_topic']}/accept")
    client.post(f"/api/programs/{p.id}/changes/{by_kind['prune_topic']}/accept")
    detail = client.post(
        f"/api/programs/{p.id}/changes/{by_kind['revise_milestone']}/reject").json()

    # map reflects exactly the accepted changes
    leg2 = next(m for m in detail["milestones"] if m["id"] == m2.id)
    assert leg2["title"] == "Architectures"  # reject left it alone
    links = {link["proposed_title"]: link for link in leg2["links"]}
    assert links["MoE routing"]["status"] == "stub"
    assert links["MoE routing"]["added_by"] == "revision"
    assert links["Old attention survey"]["status"] == "pruned"

    # revision resolved; nudge cleared (revision postdates the gate pass)
    assert detail["has_open_revision"] is False
    assert detail["revision_suggested"] is False
    # trace exists
    kinds = [e["kind"] for e in client.get(f"/api/programs/{p.id}/events").json()]
    assert "program_revision:done" in kinds
    assert "program:gate_passed" in kinds
