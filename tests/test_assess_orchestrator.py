# tests/test_assess_orchestrator.py
import json

from sqlmodel import Session, select

from adaptive_academy.engine.assess import AssessmentResult, assess_concept
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent, Assessment, Concept, KnowledgeEstimate, Topic, TopicFoundation, Track,
)


def _concept(session, level="high"):
    topic = Topic(title="Build LLMs")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["self-attention"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="self-attention")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level=level, confidence=0.6))
    session.commit()
    return topic, concept


def _llm(rubric_must, grade_score, gaps=None):
    rubric = json.dumps({"criteria": ["c"], "must_include": rubric_must,
                         "strong_signs": [], "weak_signs": [], "source_refs": []})
    grade = json.dumps({"score": grade_score, "verdict": "v", "gaps": gaps or []})
    return ScriptedLLMClient([LLMResponse(text=rubric), LLMResponse(text=grade)])


def test_weak_self_explanation_lowers_estimate_and_traces(session: Session):
    topic, concept = _concept(session, level="high")
    # rubric requires "softmax" + "QK^T"; learner omits both -> rules penalty
    llm = _llm(["softmax", "QK^T"], grade_score=0.7, gaps=["vague"])
    result = assess_concept(session, concept, "self_explanation",
                            "attention is about focusing", llm=llm)
    assert isinstance(result, AssessmentResult)

    a = session.exec(select(Assessment)).one()
    assert a.rubric_id is not None
    # 0.7 - 2*0.15 = 0.4 -> level low
    assert abs(a.score - 0.4) < 1e-6
    assert any("omitted required element" in g for g in a.gaps)

    est = session.exec(select(KnowledgeEstimate)
                       .where(KnowledgeEstimate.concept_id == concept.id)).one()
    assert est.level == "low"
    # adaptive lever moved: low knowledge -> high assistance
    assert compute_levels(est).assistance == "high"

    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    kinds = {e.kind for e in events}
    assert {"assess:probe", "assess:graded", "assess:estimate", "assess:done"}.issubset(kinds)
    assert all(e.conversation_id is None for e in events)


def test_calibration_records_predicted_vs_actual(session: Session):
    topic, concept = _concept(session)
    llm = _llm([], grade_score=0.5)  # no must_include -> no rules penalty
    assess_concept(session, concept, "calibration", "my explanation",
                   llm=llm, confidence_predicted=0.9)
    a = session.exec(select(Assessment).where(Assessment.kind == "calibration")).one()
    assert a.confidence_predicted == 0.9
    assert abs(a.confidence_actual - 0.5) < 1e-6  # actual == anchored score, NOT self-rating
    assert a.score == 0.5


def test_delta_vs_baseline(session: Session):
    topic, concept = _concept(session)
    a1 = Assessment(concept_id=concept.id, kind="self_explanation", prompt="p", score=0.3)
    session.add(a1)
    session.commit()
    llm = _llm([], grade_score=0.8)
    assess_concept(session, concept, "self_explanation", "better now", llm=llm,
                   baseline_id=a1.id)
    a2 = session.exec(select(Assessment).where(Assessment.score == 0.8)).one()
    assert abs(a2.delta - 0.5) < 1e-6
