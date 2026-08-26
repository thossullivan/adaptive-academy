import json

from sqlmodel import select

from adaptive_academy.engine.remediate import remediate_concept
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    ConceptEdge,
    Item,
    KnowledgeEstimate,
    Phase,
    Topic,
    Track,
)


def _llm() -> ScriptedLLMClient:
    return ScriptedLLMClient(
        [
            LLMResponse(
                text=json.dumps(
                    {
                        "items": [{"type": "build", "text": "repair the gap"}],
                        "revisit": None,
                    }
                )
            )
        ]
    )


def _seed_remediation_graph(
    session,
    *,
    target_level: str,
    ancestor_level: str,
    assess_ancestor: bool = True,
) -> tuple[Concept, Concept, Phase, Phase]:
    topic = Topic(title="Graph learning")
    session.add(topic)
    session.flush()
    track = Track(topic_id=topic.id, title="Graph learning")
    session.add(track)
    session.flush()
    ancestor = Concept(track_id=track.id, name="Linear algebra")
    target = Concept(track_id=track.id, name="Attention")
    session.add_all([ancestor, target])
    session.flush()
    early = Phase(track_id=track.id, title="Foundations", position=0)
    current = Phase(track_id=track.id, title="Attention", position=1)
    session.add_all([early, current])
    session.flush()
    session.add(
        Item(
            phase_id=early.id,
            text="Finish foundations",
            type="read",
            status="done",
            position=0,
            concept_refs=[ancestor.name],
        )
    )
    session.add(
        Item(
            phase_id=current.id,
            text="Study attention",
            type="read",
            status="todo",
            position=0,
            concept_refs=[target.name],
        )
    )
    score_by_level = {"low": 0.2, "medium": 0.6, "high": 0.9}
    rows = [
        KnowledgeEstimate(concept_id=target.id, level=target_level),
        KnowledgeEstimate(concept_id=ancestor.id, level=ancestor_level),
        Assessment(
            concept_id=target.id,
            kind="self_explanation",
            prompt="Explain attention",
            score=score_by_level[target_level],
            gaps=["matrix composition"],
        ),
        ConceptEdge(
            src_concept_id=target.id,
            dst_concept_id=ancestor.id,
            kind="prerequisite",
            origin="researcher",
        ),
    ]
    if assess_ancestor:
        rows.append(
            Assessment(
                concept_id=ancestor.id,
                kind="self_explanation",
                prompt="Explain linear algebra",
                score=score_by_level[ancestor_level],
            )
        )
    session.add_all(rows)
    session.commit()
    return target, ancestor, early, current


def test_low_ancestor_targets_ancestor_phase_and_prompt(session):
    target, ancestor, early, _current = _seed_remediation_graph(
        session,
        target_level="medium",
        ancestor_level="low",
    )
    llm = _llm()

    result = remediate_concept(session, target, llm=llm)

    assert result.items[0].phase_id == early.id
    assert f"ANCESTOR: {ancestor.name}" in llm.calls[0]["messages"][0]["content"]
    ancestor_events = [event for event in result.events if event.kind == "remediate:ancestor"]
    assert len(ancestor_events) == 1
    assert ancestor.name in ancestor_events[0].detail


def test_no_weaker_ancestor_keeps_current_phase_behavior(session):
    target, ancestor, _early, current = _seed_remediation_graph(
        session,
        target_level="low",
        ancestor_level="medium",
    )
    llm = _llm()

    result = remediate_concept(session, target, llm=llm)

    assert result.items[0].phase_id == current.id
    assert "ANCESTOR:" not in llm.calls[0]["messages"][0]["content"]
    assert session.exec(
        select(AgentEvent).where(AgentEvent.kind == "remediate:ancestor")
    ).first() is None
    assert ancestor.name not in llm.calls[0]["messages"][0]["content"]


def test_unassessed_default_high_ancestor_does_not_redirect_remediation(session):
    target, ancestor, _early, current = _seed_remediation_graph(
        session,
        target_level="medium",
        ancestor_level="high",
        assess_ancestor=False,
    )
    llm = _llm()

    result = remediate_concept(session, target, llm=llm)

    assert result.items[0].phase_id == current.id
    assert "ANCESTOR:" not in llm.calls[0]["messages"][0]["content"]
    assert ancestor.name not in llm.calls[0]["messages"][0]["content"]
    assert session.exec(
        select(AgentEvent).where(AgentEvent.kind == "remediate:ancestor")
    ).first() is None
