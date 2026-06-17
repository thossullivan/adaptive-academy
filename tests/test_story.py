import json

from adaptive_academy.engine.story import (
    build_story_prompt,
    gather_story_facts,
    generate_story,
    parse_story_json,
)
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment,
    Concept,
    Deliverable,
    Item,
    KnowledgeEstimate,
    Phase,
    Topic,
    TopicIntent,
    Track,
)


class FakeLLM:
    def __init__(self, text: str):
        self._text = text
        self.calls = 0

    def complete(self, system, messages, tools):  # noqa: ANN001
        self.calls += 1
        return LLMResponse(text=self._text, tool_calls=[])


def _seed(session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    session.refresh(topic)
    session.add(TopicIntent(topic_id=topic.id, goal="Ship a working transformer"))
    track = Track(topic_id=topic.id, title="LLM track", overview="o")
    session.add(track)
    session.commit()
    session.refresh(track)

    phase = Phase(track_id=track.id, title="Foundations", position=0)
    session.add(phase)
    session.commit()
    session.refresh(phase)
    # Two items, one done → 50% progress, phase not fully complete.
    session.add(Item(phase_id=phase.id, text="read paper", status="done", position=0))
    session.add(Item(phase_id=phase.id, text="build attention", status="todo", position=1))
    session.add(Deliverable(phase_id=phase.id, kind="repo", text="attention.py",
                            artifact_url="https://github.com/me/attn"))

    # Concepts at different levels.
    c_solid = Concept(track_id=track.id, name="softmax", is_load_bearing=False)
    c_shaky = Concept(track_id=track.id, name="self-attention", is_load_bearing=True)
    session.add(c_solid)
    session.add(c_shaky)
    session.commit()
    session.refresh(c_solid)
    session.refresh(c_shaky)
    session.add(KnowledgeEstimate(concept_id=c_solid.id, level="high", confidence=0.8))
    session.add(KnowledgeEstimate(concept_id=c_shaky.id, level="low", confidence=0.3))

    # Assessments: one with an improvement delta and calibration data.
    session.add(Assessment(concept_id=c_shaky.id, kind="self_explanation", prompt="p",
                           score=0.3, delta=0.12,
                           confidence_predicted=0.8, confidence_actual=0.3))
    session.add(Assessment(concept_id=c_solid.id, kind="calibration", prompt="p",
                           score=0.8, confidence_predicted=0.75, confidence_actual=0.8))
    session.commit()
    return topic


def test_gather_story_facts_reflects_real_state(session):
    topic = _seed(session)
    f = gather_story_facts(session, topic.id)

    assert f.topic_title == "Build LLMs from scratch"
    assert f.goal == "Ship a working transformer"
    assert f.items_done == 1 and f.items_total == 2 and f.progress_pct == 50
    assert f.phases_total == 1 and f.phases_completed == 0
    assert "attention.py" in f.shipped
    assert f.concepts_solid == ["softmax"]
    assert f.concepts_shaky == ["self-attention"]
    assert f.load_bearing_shaky == ["self-attention"]
    assert f.assessments_count == 2
    assert f.mean_score == 0.55
    assert any("self-attention improved" in s for s in f.improvements)
    # Predicted 0.8 vs actual 0.3 dominates → overconfident.
    assert f.calibration_note == "tends to be overconfident"


def test_build_story_prompt_includes_priority_facts(session):
    topic = _seed(session)
    f = gather_story_facts(session, topic.id)
    system, user = build_story_prompt(f)
    assert "build-in-public" in system
    assert "SHAKY LOAD-BEARING" in user and "self-attention" in user
    assert "50%" in user


def test_parse_story_json_handles_fences():
    raw = '```json\n{"headline": "You shipped attention", "narrative": ["p1", "p2"], ' \
          '"highlights": ["a", "b"]}\n```'
    headline, narrative, highlights = parse_story_json(raw)
    assert headline == "You shipped attention"
    assert narrative == ["p1", "p2"]
    assert highlights == ["a", "b"]


def test_generate_story_narrates_and_emits_events(session):
    topic = _seed(session)
    fake = FakeLLM(json.dumps({
        "headline": "Momentum on the transformer",
        "narrative": ["You shipped attention.py.", "Self-attention is still shaky."],
        "highlights": ["Shipped attention.py", "Shore up self-attention"],
    }))
    result = generate_story(session, topic.id, llm=fake)
    assert fake.calls == 1
    assert result.headline == "Momentum on the transformer"
    assert len(result.narrative) == 2
    assert result.facts.progress_pct == 50
    kinds = {e.kind for e in result.events}
    assert {"story:compose", "story:done"} <= kinds


def test_generate_story_falls_back_on_empty_narrative(session):
    topic = _seed(session)
    fake = FakeLLM(json.dumps({"headline": "", "narrative": [], "highlights": []}))
    result = generate_story(session, topic.id, llm=fake)
    assert result.headline  # non-empty fallback
    assert result.narrative  # non-empty fallback
