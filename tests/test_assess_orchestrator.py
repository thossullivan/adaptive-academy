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
from adaptive_academy.prompts import GRADE


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


def _llm(rubric_must, grade_score, gaps=None, mechanism_present=None, weak_signs=()):
    rubric = json.dumps({"criteria": ["c"], "must_include": rubric_must,
                         "strong_signs": [], "weak_signs": list(weak_signs),
                         "source_refs": []})
    grade_d = {"score": grade_score, "verdict": "v", "gaps": gaps or []}
    if mechanism_present is not None:
        grade_d["mechanism_present"] = mechanism_present
    grade = json.dumps(grade_d)
    return ScriptedLLMClient([LLMResponse(text=rubric), LLMResponse(text=grade)])


def test_weak_self_explanation_lowers_estimate_and_traces(session: Session):
    topic, concept = _concept(session, level="high")
    # The grader scores the no-mechanism answer low (band 0.30); rubric requires
    # "softmax" + "QK^T", which the learner omits -> rules gaps recorded too.
    llm = _llm(["softmax", "QK^T"], grade_score=0.3, gaps=["vague"])
    result = assess_concept(session, concept, "self_explanation",
                            "attention is about focusing", llm=llm)
    assert isinstance(result, AssessmentResult)

    a = session.exec(select(Assessment)).one()
    assert a.rubric_id is not None
    # 0.3 is already below the omission ceiling (0.70) -> unchanged -> level low
    assert abs(a.score - 0.3) < 1e-6
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


def test_mechanism_absent_caps_score_at_developing(session: Session):
    # A confidently fluent answer the grader marks mechanism_present=false must be capped at
    # 0.50 no matter how high the raw score — the code-enforced illusion-of-competence guard.
    topic, concept = _concept(session, level="high")
    llm = _llm([], grade_score=0.9, mechanism_present=False)
    assess_concept(session, concept, "self_explanation", "lots of fluent words", llm=llm)
    a = session.exec(select(Assessment)).one()
    assert a.score == 0.5  # capped down from 0.9
    events = {e.kind for e in session.exec(select(AgentEvent)).all()}
    assert "assess:mechanism" in events


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


def test_assessment_records_the_grading_prompt_tag(session: Session):
    _, concept = _concept(session)
    result = assess_concept(session, concept, "self_explanation", "softmax over QK^T",
                            llm=_llm([], grade_score=0.8))
    # The tag of the prompt that produced the grade (not the rubric prompt that ran first),
    # and the same tag the trace says ran.
    assert result.assessment.prompt_tag == GRADE.tag
    traced = session.exec(select(AgentEvent.detail).where(AgentEvent.kind == "prompt")).all()
    assert traced == [GRADE.tag]


def test_artifact_review_through_assess_concept_records_the_grade_tag(session: Session):
    _, concept = _concept(session)
    grade = json.dumps({"score": 0.9, "verdict": "v", "gaps": [], "mechanism_present": True})
    result = assess_concept(session, concept, "artifact_review", "my repo",
                            llm=ScriptedLLMClient([LLMResponse(text=grade)]))
    # assess_concept grades every kind with GRADE (the ship review's ASSESS_ARTIFACT is a
    # different path, engine/artifact.py).
    assert result.assessment.prompt_tag == GRADE.tag


def test_assessment_written_without_a_model_has_no_prompt_tag(session: Session):
    _, concept = _concept(session)
    a = Assessment(concept_id=concept.id, kind="self_explanation", prompt="p", score=0.3)
    session.add(a)
    session.commit()
    session.refresh(a)
    assert a.prompt_tag is None


def test_formula_must_include_in_other_notation_is_not_capped(session: Session):
    # The live "Gradient of the cost" case: a cached rubric whose must_include items are Unicode
    # formulas, and a correct ASCII answer with other variable names and the MSE convention.
    # Formula items are left to the grader (named in its prompt), not hard gaps that cap 0.70.
    _, concept = _concept(session)
    formulas = ["Xᵀ(Xθ − y)", "(1/m)Xᵀ(Xθ − y)", "residual r = Xθ − y", "∇J(θ)", "½‖Xθ − y‖²"]
    llm = _llm(formulas, grade_score=0.9, mechanism_present=True)
    assess_concept(session, concept, "self_explanation",
                   "For least squares the gradient is (2/n) X^T (Xw - y)", llm=llm)
    a = session.exec(select(Assessment)).one()
    assert a.score == 0.9
    assert not any(g.startswith("omitted required element") for g in a.gaps)
    grade_user = llm.calls[1]["messages"][0]["content"]
    assert "EXPECTED FORMULAS" in grade_user
    assert all(f in grade_user for f in formulas)
    soft = session.exec(select(AgentEvent).where(AgentEvent.kind == "assess:rules-soft")).one()
    assert soft.detail.startswith("5 item(s) left to the grader")
    assert session.exec(select(AgentEvent).where(AgentEvent.kind == "assess:rules")).first() \
        is None


def test_word_must_include_still_caps_when_missing(session: Session):
    _, concept = _concept(session)
    llm = _llm(["chain rule", "Xᵀ(Xθ − y)"], grade_score=0.9, mechanism_present=True)
    assess_concept(session, concept, "self_explanation",
                   "For least squares the gradient is (2/n) X^T (Xw - y)", llm=llm)
    a = session.exec(select(Assessment)).one()
    assert a.score == 0.7
    assert "omitted required element: chain rule" in a.gaps
    assert not any("Xᵀ" in g for g in a.gaps)


def test_uncertain_word_must_include_goes_to_the_grader_uncapped(session: Session):
    # "regularization" is there, "L2" is not: a near miss the word check can't settle, so the
    # grader is asked (POSSIBLY MISSING) and the code doesn't cap the score.
    _, concept = _concept(session)
    llm = _llm(["L2 regularization", "residual"], grade_score=0.9, mechanism_present=True)
    assess_concept(session, concept, "self_explanation",
                   "L1 regularization shrinks weights toward zero", llm=llm)
    a = session.exec(select(Assessment)).one()
    assert a.score == 0.7  # "residual" is confidently absent: a hard gap
    assert a.gaps == ["omitted required element: residual"]
    grade_user = llm.calls[1]["messages"][0]["content"]
    assert "POSSIBLY MISSING:\n- L2 regularization" in grade_user
    assert "residual" not in grade_user.split("<<<RESPONSE>>>")[0].split("POSSIBLY MISSING")[1]
    soft = session.exec(select(AgentEvent).where(AgentEvent.kind == "assess:rules-soft")).one()
    assert soft.detail == "1 item(s) left to the grader: L2 regularization"


def test_negated_weak_sign_goes_to_the_grader_uncapped(session: Session):
    _, concept = _concept(session)
    llm = _llm(["converge"], grade_score=0.9, mechanism_present=True,
               weak_signs=["always converge"])
    assess_concept(session, concept, "self_explanation",
                   "SGD doesn't always converge with a fixed step", llm=llm)
    a = session.exec(select(Assessment)).one()
    assert a.score == 0.9 and a.gaps == []
    grade_user = llm.calls[1]["messages"][0]["content"]
    assert "POSSIBLE MISCONCEPTIONS:\n- always converge" in grade_user


def test_full_weak_sign_still_caps(session: Session):
    _, concept = _concept(session)
    llm = _llm(["converge"], grade_score=0.9, mechanism_present=True,
               weak_signs=["always converge"])
    assess_concept(session, concept, "self_explanation",
                   "SGD always converges with a fixed step", llm=llm)
    a = session.exec(select(Assessment)).one()
    assert a.score == 0.5
    assert a.gaps == ["contains likely misconception: always converge"]
