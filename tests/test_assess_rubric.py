# tests/test_assess_rubric.py
import json

from sqlmodel import Session, select

from adaptive_academy.engine.assess import ensure_rubric
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import Concept, Rubric, Topic, TopicFoundation, Track


def _concept(session):
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
    return concept


def _rubric_llm():
    payload = json.dumps({"criteria": ["explain scaled dot-product"],
                          "must_include": ["softmax", "QK^T"], "strong_signs": [],
                          "weak_signs": ["picks the max"], "source_refs": []})
    return ScriptedLLMClient([LLMResponse(text=payload)])


def test_ensure_rubric_generates_then_caches(session: Session):
    concept = _concept(session)
    llm = _rubric_llm()
    r1 = ensure_rubric(session, concept, llm=llm)
    assert r1.must_include == ["softmax", "QK^T"]
    assert len(llm.calls) == 1
    # second call: cached, no further LLM call
    r2 = ensure_rubric(session, concept, llm=llm)
    assert r2.id == r1.id and len(llm.calls) == 1
    assert len(session.exec(select(Rubric)).all()) == 1
