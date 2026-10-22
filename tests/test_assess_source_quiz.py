import json

from adaptive_academy.engine.assess import AnchorError, assess_concept
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Concept, KnowledgeEstimate, ReferenceAnchor, SourceDoc, Topic, Track,
)
from adaptive_academy.prompts import grade_prompt


def _seed(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
    src = SourceDoc(topic_id=topic.id, title="s", url="u", status="accepted")
    session.add(src)
    session.commit()
    anchor = ReferenceAnchor(source_doc_id=src.id, concept_id=concept.id,
                             question="Why subtract the max in softmax?",
                             reference_answer="for numerical stability",
                             key_points=["numerical stability", "overflow"])
    session.add(anchor)
    session.commit()
    return topic, concept, anchor


def test_source_quiz_grades_against_anchor(session):
    topic, concept, anchor = _seed(session)
    grade = json.dumps({"score": 0.9, "verdict": "good", "gaps": [],
                        "missing_required": [], "misconceptions_committed": []})
    llm = ScriptedLLMClient([LLMResponse(text=grade)])
    res = assess_concept(session, concept, "source_quiz",
                         "it avoids overflow for numerical stability", llm=llm)
    assert res.assessment.anchor_id == anchor.id
    assert res.assessment.rubric_id is None
    assert res.assessment.prompt == anchor.question
    assert len(llm.calls) == 1  # NO rubric call — only the grade call
    assert res.assessment.prompt_tag == grade_prompt().tag


def test_source_quiz_omitted_key_point_named_by_the_grader_is_capped(session):
    topic, concept, anchor = _seed(session)
    grade = json.dumps({"score": 0.9, "verdict": "confident", "gaps": [],
                        "missing_required": ["numerical stability"],
                        "misconceptions_committed": []})
    llm = ScriptedLLMClient([LLMResponse(text=grade)])
    res = assess_concept(session, concept, "source_quiz", "it just works", llm=llm)
    assert res.assessment.score == 0.7
    assert res.assessment.gaps == ["omitted required element: numerical stability"]


def test_source_quiz_key_points_word_and_formula_are_required_elements(session):
    # criteria == key_points for a source quiz, and every key point (word or formula) is a
    # REQUIRED ELEMENT the grader judges by meaning.
    topic, concept, anchor = _seed(session)
    anchor.key_points = ["numerical stability", "softmax(x - max(x))"]
    session.add(anchor)
    session.commit()
    grade = json.dumps({"score": 0.9, "verdict": "good", "gaps": [], "missing_required": [],
                        "misconceptions_committed": []})
    llm = ScriptedLLMClient([LLMResponse(text=grade)])
    res = assess_concept(session, concept, "source_quiz",
                         "for numerical stability subtract the largest logit", llm=llm)
    user = llm.calls[0]["messages"][0]["content"]
    required = user.split("REQUIRED ELEMENTS:", 1)[1].split("KNOWN MISCONCEPTIONS", 1)[0]
    assert "- softmax(x - max(x))" in required and "- numerical stability" in required
    assert "KNOWN MISCONCEPTIONS: (none)" in user
    assert res.assessment.score == 0.9 and res.assessment.gaps == []


def test_source_quiz_without_anchor_raises(session):
    topic, concept, anchor = _seed(session)
    session.delete(anchor)
    session.commit()
    llm = ScriptedLLMClient([])
    try:
        assess_concept(session, concept, "source_quiz", "x", llm=llm)
        assert False, "expected AnchorError"
    except AnchorError:
        pass


def test_source_quiz_rejects_another_concepts_anchor(session):
    # An explicit anchor_id belonging to a DIFFERENT concept must not be graded
    # against this concept (cross-concept reuse via the public param).
    topic, concept, anchor = _seed(session)
    other = Concept(track_id=concept.track_id, name="layernorm")
    session.add(other)
    session.commit()
    llm = ScriptedLLMClient([])  # must raise before any LLM call
    try:
        assess_concept(session, other, "source_quiz", "x", llm=llm, anchor_id=anchor.id)
        assert False, "expected AnchorError"
    except AnchorError:
        pass
