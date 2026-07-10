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


class _FlakyResearcher:
    """Returns sources for most angles but raises for one (a transient failure)."""

    def __init__(self, ok_angle: str, boom_angle: str):
        self._ok, self._boom = ok_angle, boom_angle

    def search(self, brief):
        if brief.angle == self._boom:
            raise RuntimeError("529 Overloaded")
        if brief.angle == self._ok:
            return [RawSource(title="S", url="https://s.com", tier=1, relevance=0.9)]
        return []


def test_research_topic_survives_a_single_angle_failure(session: Session):
    topic, intent = _topic_with_intent(session)
    researcher = _FlakyResearcher(ok_angle="foundational_papers", boom_angle="critiques")
    research_topic(session, topic, intent, researcher=researcher,
                   llm=_foundation_llm(), max_subagents=5)

    # The fan-out did NOT abort: the healthy angle's source persisted.
    sources = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic.id)).all()
    assert len(sources) == 1
    # The failed angle is traced as an error event, not a silent drop.
    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    assert any(e.kind == "research:subagent_error" and "critiques" in e.detail for e in events)
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


class _FailFirstCallResearcher:
    """Fails an angle's FIRST call, succeeds on the retry sweep. Thread-safe."""

    def __init__(self, flaky_angle: str):
        import threading

        self._flaky_angle = flaky_angle
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def search(self, brief):
        with self._lock:
            first_call = brief.angle not in self._seen
            self._seen.add(brief.angle)
        if first_call and brief.angle == self._flaky_angle:
            raise RuntimeError("connection reset by transient blip")
        return [RawSource(title=f"{brief.angle} source",
                          url=f"https://e.com/{brief.angle}", tier=2)]


def test_topic_transient_angle_recovers_on_second_chance_sweep(session: Session):
    topic, intent = _topic_with_intent(session)
    result = research_topic(
        session, topic, intent,
        researcher=_FailFirstCallResearcher("foundational_papers"),
        llm=_foundation_llm(), max_subagents=5)

    kinds = [e.kind for e in result.events]
    assert "research:subagent_error" not in kinds
    retries = [e for e in result.events if e.kind == "research:subagent_retry"]
    assert len(retries) == 1
    assert retries[0].detail == "foundational_papers: recovered 1 sources"
    # the recovered angle's source made it into the persisted set
    sources = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic.id)).all()
    assert any(s.angle == "foundational_papers" for s in sources)


def test_topic_subagent_error_detail_includes_exception_message(session: Session):
    topic, intent = _topic_with_intent(session)

    class PersistentFailResearcher:
        def search(self, brief):
            if brief.angle == "critiques":
                raise RuntimeError("529 overloaded upstream")
            return [RawSource(title=f"{brief.angle} source",
                              url=f"https://e.com/{brief.angle}", tier=2)]

    result = research_topic(session, topic, intent,
                            researcher=PersistentFailResearcher(),
                            llm=_foundation_llm(), max_subagents=5)
    errs = [e for e in result.events if e.kind == "research:subagent_error"]
    assert len(errs) == 1
    assert "RuntimeError: 529 overloaded upstream" in errs[0].detail
