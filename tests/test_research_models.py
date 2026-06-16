from sqlmodel import Session, select

from adaptive_academy.models import (
    AgentEvent,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
)


def test_topic_intent_roundtrip(session: Session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    session.add(
        TopicIntent(
            topic_id=topic.id,
            goal="Understand transformers end to end",
            prior_knowledge="Strong math, some PyTorch",
            time_budget="~10 hrs/week",
        )
    )
    session.commit()
    intent = session.exec(select(TopicIntent)).one()
    assert intent.goal.startswith("Understand")
    assert intent.time_budget == "~10 hrs/week"


def test_sourcedoc_defaults_and_json_foundation(session: Session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(
        SourceDoc(topic_id=topic.id, title="Attention Is All You Need", url="https://arxiv.org/abs/1706.03762", tier=1)
    )
    session.add(
        TopicFoundation(
            topic_id=topic.id,
            overview="Transformers replace recurrence with attention.",
            key_concepts=["self-attention", "positional encoding"],
            prerequisite_map={"self-attention": ["dot product", "softmax"]},
        )
    )
    session.commit()
    sd = session.exec(select(SourceDoc)).one()
    assert sd.status == "proposed"
    assert sd.added_by == "researcher"
    assert sd.rank == 0
    fnd = session.exec(select(TopicFoundation)).one()
    assert fnd.key_concepts == ["self-attention", "positional encoding"]
    assert fnd.prerequisite_map["self-attention"] == ["dot product", "softmax"]


def test_agentevent_attaches_to_topic(session: Session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(AgentEvent(topic_id=topic.id, kind="research:done", detail="3 sources"))
    session.commit()
    ev = session.exec(select(AgentEvent)).one()
    assert ev.topic_id == topic.id
    assert ev.conversation_id is None
