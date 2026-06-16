import json

from sqlmodel import select

from adaptive_academy.engine.remediate import RemediationError, remediate_concept
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, Item, KnowledgeEstimate, Phase, Topic, Track,
)


def _seed(session, gaps):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax", is_load_bearing=True)
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="low", confidence=0.3))
    p0 = Phase(track_id=track.id, title="P0", position=0)
    p1 = Phase(track_id=track.id, title="P1", position=1)
    session.add(p0)
    session.add(p1)
    session.commit()
    session.add(Item(phase_id=p0.id, text="existing", type="read", status="todo", position=0))
    a = Assessment(concept_id=concept.id, kind="self_explanation", prompt="p",
                   score=0.3, gaps=gaps)
    session.add(a)
    session.commit()
    return topic, track, concept, p0, p1, a


def _llm(items, revisit=None):
    return ScriptedLLMClient([LLMResponse(text=json.dumps(
        {"items": items, "revisit": revisit}))])


def test_remediate_injects_items_into_current_phase(session):
    topic, track, concept, p0, p1, a = _seed(session, ["gap A", "gap B"])
    llm = _llm([{"type": "build", "text": "attack A"}, {"type": "write", "text": "attack B"}])
    res = remediate_concept(session, concept, llm=llm)
    assert len(res.items) == 2
    rem = [i for i in session.exec(select(Item)).all() if i.added_by == "remediation"]
    assert len(rem) == 2
    assert all(i.phase_id == p0.id for i in rem)
    assert all(i.concept_refs == ["softmax"] for i in rem)
    kinds = {e.kind for e in res.events}
    assert {"remediate:probe", "remediate:generated", "remediate:placed",
            "remediate:done"} <= kinds


def test_remediate_is_idempotent_for_same_gaps(session):
    topic, track, concept, p0, p1, a = _seed(session, ["gap A"])
    res1 = remediate_concept(session, concept, llm=_llm([{"type": "build", "text": "x"}]))
    assert len(res1.items) == 1
    res2 = remediate_concept(session, concept, llm=_llm([{"type": "build", "text": "y"}]))
    assert res2.items == []


def test_remediate_new_gap_injects_even_with_old_open(session):
    topic, track, concept, p0, p1, a = _seed(session, ["gap A"])
    remediate_concept(session, concept, llm=_llm([{"type": "build", "text": "x"}]))
    a2 = Assessment(concept_id=concept.id, kind="self_explanation", prompt="p",
                    score=0.3, gaps=["gap A", "gap C"])
    session.add(a2)
    session.commit()
    res = remediate_concept(session, concept, llm=_llm([{"type": "build", "text": "z"}]))
    assert len(res.items) == 1


def test_remediate_revisit_lands_in_later_phase(session):
    topic, track, concept, p0, p1, a = _seed(session, ["gap A"])
    res = remediate_concept(session, concept,
                            llm=_llm([{"type": "build", "text": "x"}],
                                     revisit={"text": "revisit softmax"}))
    revisits = [i for i in res.items if i.remediation_key.startswith("revisit:")]
    assert len(revisits) == 1
    assert revisits[0].phase_id == p1.id


def test_remediate_raises_when_track_has_no_phases(session):
    # A concept-bearing track with zero phases (reachable via markdown import or an
    # LLM that returned no phases) must 400 cleanly, not 500 on an empty-list index.
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    session.add(Assessment(concept_id=concept.id, kind="self_explanation", prompt="p",
                           score=0.3, gaps=["gap A"]))
    session.commit()
    try:
        remediate_concept(session, concept, llm=_llm([{"type": "build", "text": "x"}]))
        assert False, "expected RemediationError"
    except RemediationError:
        pass


def test_remediate_raises_without_assessment(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="bare")
    session.add(concept)
    session.commit()
    try:
        remediate_concept(session, concept, llm=_llm([]))
        assert False, "expected RemediationError"
    except RemediationError:
        pass
