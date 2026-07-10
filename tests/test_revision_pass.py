import json

import pytest
from sqlmodel import select

from adaptive_academy.engine.revision import (
    REVISION_ANGLES,
    build_revision_briefs,
    run_revision,
    serialize_map,
    validate_change,
)
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    MapChange, MapRevision, Milestone, Program, ProgramIntent, ProgramTopicLink,
)


def _program(session, *, started_first_leg=True):
    p = Program(title="PhD prep", goal_statement="research-ready")
    session.add(p)
    session.commit()
    session.add(ProgramIntent(program_id=p.id, focus_area="custom LLMs"))
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0,
                   gate_status="passed")
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    session.add(m1)
    session.add(m2)
    session.commit()
    l1 = ProgramTopicLink(milestone_id=m1.id, proposed_title="Backprop",
                          status="started" if started_first_leg else "stub")
    l2 = ProgramTopicLink(milestone_id=m2.id, proposed_title="Attention", status="stub")
    session.add(l1)
    session.add(l2)
    session.commit()
    return p, m1, m2, l1, l2


def test_briefs_fill_since_label():
    briefs = build_revision_briefs("PhD prep", "custom LLMs", "July 2026")
    assert [b.angle for b in briefs] == [a for a, _ in REVISION_ANGLES]
    assert "July 2026" in briefs[0].query
    assert "custom LLMs" in briefs[0].query


def test_serialize_map_carries_ids_and_statuses(session):
    p, m1, m2, l1, l2 = _program(session)
    text = serialize_map(session, p)
    assert f"milestone id={m1.id}" in text and "[gate: passed]" in text
    assert f"link id={l2.id}" in text and "(stub)" in text


def test_validate_change_rules(session):
    p, m1, m2, l1, l2 = _program(session)
    # untouchable: m1 has a started link AND a passed gate
    assert validate_change(session, p, "revise_milestone",
                           {"milestone_id": m1.id, "title": "x"}) is not None
    assert validate_change(session, p, "prune_milestone",
                           {"milestone_id": m1.id}) is not None
    assert validate_change(session, p, "prune_topic", {"link_id": l1.id}) is not None
    # allowed: un-started leg / stub link
    assert validate_change(session, p, "revise_milestone",
                           {"milestone_id": m2.id, "title": "x"}) is None
    assert validate_change(session, p, "prune_topic", {"link_id": l2.id}) is None
    # unresolvable id
    assert validate_change(session, p, "add_topic",
                           {"milestone_id": 999, "title": "x"}) is not None
    # duplicate un-started title (case-insensitive)
    assert validate_change(session, p, "add_topic",
                           {"milestone_id": m2.id, "title": "ATTENTION"}) is not None
    # unknown kind
    assert validate_change(session, p, "explode", {}) is not None


SYNTH = {
    "map_health": "solid but MoE is missing",
    "changes": [
        {"kind": "add_topic", "payload": {"milestone_id": 0, "title": "MoE routing"},
         "why": "field moved", "source_urls": ["https://e.com/moe"]},
        {"kind": "revise_milestone", "payload": {"milestone_id": -1, "title": "nope"},
         "why": "targets started leg", "source_urls": []},
    ],
}


def _synth_for(m2_id: int, m1_id: int) -> str:
    payload = json.loads(json.dumps(SYNTH))
    payload["changes"][0]["payload"]["milestone_id"] = m2_id
    payload["changes"][1]["payload"]["milestone_id"] = m1_id  # invalid: started+passed
    return json.dumps(payload)


def test_run_revision_persists_valid_changes_and_drops_invalid(session):
    p, m1, m2, l1, l2 = _program(session)
    researcher = ScriptedResearcherClient({
        "whats_new": [RawSource(title="MoE", url="https://e.com/moe", tier=1)],
    })
    llm = ScriptedLLMClient([LLMResponse(text=_synth_for(m2.id, m1.id))])
    result = run_revision(session, p, session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == p.id)).first(),
        researcher=researcher, llm=llm)

    assert result.revision.map_health == "solid but MoE is missing"
    assert len(result.changes) == 1  # the started-leg change was dropped
    assert result.changes[0].kind == "add_topic"
    assert result.changes[0].status == "proposed"
    kinds = [e.kind for e in result.events]
    assert "program_revision:plan" in kinds
    assert "program_revision:changes_dropped" in kinds
    assert all(e.program_id == p.id for e in result.events)


def test_run_revision_refuses_open_revision_and_zero_sources(session):
    p, m1, m2, l1, l2 = _program(session)
    intent = session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == p.id)).first()

    class EmptyResearcher:
        def search(self, brief):
            return []

    with pytest.raises(ValueError, match="no sources"):
        run_revision(session, p, intent, researcher=EmptyResearcher(),
                     llm=ScriptedLLMClient([]))
    assert session.exec(select(MapRevision)).all() == []  # nothing persisted

    # seed an open revision → second run refused
    rev = MapRevision(program_id=p.id)
    session.add(rev)
    session.commit()
    session.add(MapChange(revision_id=rev.id, kind="add_topic",
                          payload={"milestone_id": m2.id, "title": "X"}))
    session.commit()
    with pytest.raises(ValueError, match="open revision"):
        run_revision(session, p, intent,
                     researcher=ScriptedResearcherClient({}),
                     llm=ScriptedLLMClient([]))
