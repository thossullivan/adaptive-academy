import json

from sqlmodel import Session, col, select

from adaptive_academy.engine.curriculum import generate_curriculum
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    ConceptEdge,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
)


def _setup(session: Session):
    topic = Topic(title="Transformers")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="Build a transformer")
    foundation = TopicFoundation(
        topic_id=topic.id,
        key_concepts=["Transformer", "Attention", "Softmax"],
        prerequisite_map={
            "Transformer": ["attention"],
            "Attention": ["Softmax", "Unknown"],
        },
    )
    source = SourceDoc(
        topic_id=topic.id,
        title="Attention",
        url="https://example.test/attention",
        status="accepted",
    )
    session.add_all([intent, foundation, source])
    session.commit()
    return topic, intent, foundation, [source]


def _llm(calls: int = 1) -> ScriptedLLMClient:
    payload = json.dumps({"overview": "A path", "phases": []})
    return ScriptedLLMClient([LLMResponse(text=payload) for _ in range(calls)])


def _current_researcher_edges(session: Session) -> list[ConceptEdge]:
    return session.exec(
        select(ConceptEdge).where(
            ConceptEdge.origin == "researcher",
            col(ConceptEdge.valid_until).is_(None),
        )
    ).all()


def test_curriculum_populates_researcher_edges_and_logs_unresolved(session: Session):
    topic, intent, foundation, sources = _setup(session)

    generate_curriculum(session, topic, intent, foundation, sources, llm=_llm())

    edges = _current_researcher_edges(session)
    assert len(edges) == 2
    assert {edge.kind for edge in edges} == {"prerequisite"}
    event = session.exec(
        select(AgentEvent).where(
            AgentEvent.topic_id == topic.id,
            AgentEvent.kind == "graph:edges",
        )
    ).one()
    assert event.detail == "2 edges, 1 unresolved"


def test_curriculum_regeneration_invalidates_old_edges_and_inserts_new(session: Session):
    topic, intent, foundation, sources = _setup(session)
    llm = _llm(calls=2)
    generate_curriculum(session, topic, intent, foundation, sources, llm=llm)
    original_ids = {edge.id for edge in _current_researcher_edges(session)}

    generate_curriculum(session, topic, intent, foundation, sources, llm=llm)

    rows = session.exec(select(ConceptEdge).order_by(ConceptEdge.id)).all()
    current = [edge for edge in rows if edge.valid_until is None]
    historical = [edge for edge in rows if edge.valid_until is not None]
    assert len(rows) == 4
    assert len(current) == len(historical) == 2
    assert {edge.id for edge in historical} == original_ids
    assert not original_ids.intersection(edge.id for edge in current)
