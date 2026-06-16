import json

from sqlmodel import Session, select

from adaptive_academy.engine.research import ResearchResult, research_topic
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import AgentEvent, SourceDoc, Topic, TopicFoundation, TopicIntent


def _topic_with_intent(session: Session) -> tuple[Topic, TopicIntent]:
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="learn transformers", prior_knowledge="strong", time_budget="10h")
    session.add(intent)
    session.commit()
    return topic, intent


def _foundation_llm() -> ScriptedLLMClient:
    payload = json.dumps({"overview": "o", "key_concepts": ["self-attention"], "prerequisite_map": {}})
    return ScriptedLLMClient([LLMResponse(text=payload)])


def _researcher() -> ScriptedResearcherClient:
    # foundational_papers surfaces a duplicate of the canonical_tutorials url to exercise dedup
    return ScriptedResearcherClient(
        {
            "foundational_papers": [
                RawSource(title="Attention", url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.95, summary="s"),
                RawSource(title="Dup", url="http://www.arxiv.org/abs/1706.03762/", tier=1, relevance=0.5),
            ],
            "canonical_tutorials": [
                RawSource(title="Karpathy", url="https://youtube.com/watch?v=kCc8FmEb1nY", tier=2, relevance=0.8, summary="s"),
            ],
            "key_concepts": [],
            "reference_implementations": [],
            "critiques": [],
        }
    )


def test_research_topic_persists_and_traces(session: Session):
    topic, intent = _topic_with_intent(session)
    result = research_topic(session, topic, intent, researcher=_researcher(), llm=_foundation_llm(), max_subagents=5)

    assert isinstance(result, ResearchResult)

    # Sources: 3 surfaced, 1 duplicate removed -> 2 persisted, all proposed
    sources = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic.id)).all()
    assert len(sources) == 2
    assert {s.status for s in sources} == {"proposed"}
    # ranked: arxiv (tier1) before youtube (tier2)
    ordered = sorted(sources, key=lambda s: s.rank)
    assert "arxiv" in ordered[0].url
    assert ordered[0].rank == 0 and ordered[1].rank == 1
    assert ordered[0].angle == "foundational_papers"

    # Foundation persisted
    fnd = session.exec(select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)).one()
    assert fnd.key_concepts == ["self-attention"]

    # Trace: one subagent event per brief (5), all topic-scoped
    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    subagent = [e for e in events if e.kind == "research:subagent"]
    assert len(subagent) == 5
    assert all(e.conversation_id is None for e in events)
    assert any(e.kind == "research:done" for e in events)


def test_research_topic_caps_reading_list_and_logs_drop(session: Session):
    topic, intent = _topic_with_intent(session)
    many = [RawSource(title=f"S{i}", url=f"https://s{i}.com", tier=1, relevance=0.9) for i in range(20)]
    researcher = ScriptedResearcherClient({"foundational_papers": many})
    research_topic(session, topic, intent, researcher=researcher, llm=_foundation_llm(), max_subagents=1, cap=12)

    sources = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic.id)).all()
    assert len(sources) == 12  # capped
    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    assert any(e.kind == "research:capped" for e in events)
