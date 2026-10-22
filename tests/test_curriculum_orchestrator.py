# tests/test_curriculum_orchestrator.py
import json

from sqlmodel import Session, select

from adaptive_academy.engine.curriculum import CurriculumResult, generate_curriculum
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent, Concept, ConceptEdge, Deliverable, Item, KnowledgeEstimate, Phase, Sidebar,
    SourceDoc, Topic, TopicFoundation, TopicIntent, Track,
)


def _setup(session: Session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="build a GPT",
                         prior_knowledge="strong", time_budget="10h/wk")
    fnd = TopicFoundation(topic_id=topic.id, overview="ov",
                          key_concepts=["self-attention", "linear algebra"],
                          prerequisite_map={"self-attention": ["linear algebra"]})
    src = SourceDoc(topic_id=topic.id, title="Attention", url="u", tier=1,
                    summary="s", status="accepted", rank=0)
    session.add_all([intent, fnd, src])
    session.commit()
    return topic, intent, fnd, [src]


def _llm() -> ScriptedLLMClient:
    payload = json.dumps({
        "overview": "a path",
        "phases": [
            {"title": "Foundations", "est_hours": "Wk1",
             "items": [{"type": "read", "text": "la refresher",
                        "concept_refs": ["linear algebra"]}],
             "deliverable": {"kind": "blog", "text": "notes",
                             "acceptance_criteria": ["clear"]}},
            {"title": "Build", "est_hours": "Wk2-5",
             "items": [{"type": "build", "text": "nanoGPT",
                        "concept_refs": ["self-attention"]}],
             "deliverable": {"kind": "repo", "text": "repo",
                             "acceptance_criteria": ["trains"]}},
        ],
        "sidebars": [{"kind": "math_refresh", "title": "Math", "body": "la"}],
    })
    return ScriptedLLMClient([LLMResponse(text=payload)])


def test_generate_persists_full_track_and_traces(session: Session):
    topic, intent, fnd, sources = _setup(session)
    result = generate_curriculum(session, topic, intent, fnd, sources, llm=_llm())
    assert isinstance(result, CurriculumResult)

    track = session.exec(select(Track).where(Track.topic_id == topic.id)).one()
    assert track.overview == "a path"
    phases = session.exec(select(Phase).where(Phase.track_id == track.id)).all()
    assert len(phases) == 2
    assert [p.position for p in sorted(phases, key=lambda x: x.position)] == [0, 1]
    assert session.exec(select(Deliverable)).all() and session.exec(select(Item)).all()
    assert session.exec(select(Sidebar)).all()

    # Concepts materialized with load-bearing flags + seeded estimates
    concepts = session.exec(select(Concept).where(Concept.track_id == track.id)).all()
    by_name = {c.name: c for c in concepts}
    assert by_name["linear algebra"].is_load_bearing is True   # depended upon
    assert by_name["self-attention"].is_load_bearing is False
    estimates = session.exec(select(KnowledgeEstimate)).all()
    assert len(estimates) == len(concepts) and all(e.level == "high" for e in estimates)
    assert len(session.exec(select(ConceptEdge)).all()) == 1

    # Spaced revisit: linear algebra referenced only in P1 -> injected into a later phase
    items = session.exec(select(Item)).all()
    revisit = [it for it in items if it.text.startswith("Revisit")]
    assert any("linear algebra" in it.concept_refs for it in revisit)

    # Trace: topic-scoped events, one per step incl. done
    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    kinds = {e.kind for e in events}
    assert {"curriculum:plan", "curriculum:generated", "curriculum:concepts",
            "curriculum:done"}.issubset(kinds)
    assert all(e.conversation_id is None for e in events)
    assert "concepts:repaired" not in kinds  # clean names: nothing to repair


_LEAKY = "Gradient of the cost: ∇J(θ)=Xᵀ(Xθ−y) (divided by m if using the averaged cost)"


def test_foundation_with_leaky_names_is_repaired_before_concepts_exist(session: Session):
    """A foundation stored before the name checks (or edited) never reaches a Concept row,
    a probe, or the curriculum prompt with a name that states its answer."""
    topic = Topic(title="GD")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="g", prior_knowledge="p", time_budget="t")
    fnd = TopicFoundation(topic_id=topic.id, overview="ov",
                          key_concepts=[_LEAKY, "Batch gradient descent update"],
                          prerequisite_map={"Batch gradient descent update": [_LEAKY]})
    session.add_all([intent, fnd])
    session.commit()
    payload = json.dumps({"overview": "p", "phases": [
        {"title": "A", "items": [{"type": "build", "text": "derive",
                                  "concept_refs": [_LEAKY]}],
         "deliverable": {"kind": "blog", "text": "t"}},
        {"title": "B", "items": [{"type": "build", "text": "implement",
                                  "concept_refs": ["Batch gradient descent update"]}],
         "deliverable": {"kind": "repo", "text": "t"}},
    ]})
    llm = ScriptedLLMClient([LLMResponse(text=payload)])
    generate_curriculum(session, topic, intent, fnd, [], llm=llm)

    sent = llm.calls[0]["messages"][0]["content"]
    assert "∇" not in sent and "Gradient of the cost" in sent
    names = {c.name for c in session.exec(select(Concept)).all()}
    assert names == {"Gradient of the cost", "Batch gradient descent update"}
    session.refresh(fnd)
    assert fnd.key_concepts == ["Gradient of the cost", "Batch gradient descent update"]
    assert fnd.prerequisite_map == {"Batch gradient descent update": ["Gradient of the cost"]}
    refs = [c for it in session.exec(select(Item)).all() for c in it.concept_refs]
    assert _LEAKY not in refs and "Gradient of the cost" in refs
    assert len(session.exec(select(ConceptEdge)).all()) == 1
    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    repaired = [e.detail for e in events if e.kind == "concepts:repaired"]
    assert len(repaired) == 1 and repaired[0].startswith("WARN ")
