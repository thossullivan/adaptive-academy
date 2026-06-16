import json

from adaptive_academy.engine.assess import AnchorError, assess_concept
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Concept, KnowledgeEstimate, ReferenceAnchor, SourceDoc, Topic, Track,
)


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
    grade = json.dumps({"score": 0.9, "verdict": "good", "gaps": []})
    llm = ScriptedLLMClient([LLMResponse(text=grade)])
    res = assess_concept(session, concept, "source_quiz",
                         "it avoids overflow for numerical stability", llm=llm)
    assert res.assessment.anchor_id == anchor.id
    assert res.assessment.rubric_id is None
    assert res.assessment.prompt == anchor.question
    assert len(llm.calls) == 1  # NO rubric call — only the grade call


def test_source_quiz_rules_layer_penalizes_omitted_key_point(session):
    topic, concept, anchor = _seed(session)
    grade = json.dumps({"score": 0.9, "verdict": "confident", "gaps": []})
    llm = ScriptedLLMClient([LLMResponse(text=grade)])
    res = assess_concept(session, concept, "source_quiz", "it just works", llm=llm)
    assert res.assessment.score < 0.9
    assert any("omitted required element" in g for g in res.assessment.gaps)


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
