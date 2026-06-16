from sqlmodel import Session, select

from adaptive_academy.models import (
    Assessment, Concept, KnowledgeEstimate, RecallPrompt, ReferenceAnchor, Rubric,
    SourceDoc, SRSCard, Topic, Track,
)
from adaptive_academy.models import _now


def test_assessor_tables(session: Session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="self-attention", is_load_bearing=True)
    src = SourceDoc(topic_id=topic.id, title="Attention", url="u", tier=1)
    session.add_all([concept, src])
    session.commit()

    session.add(Rubric(concept_id=concept.id, criteria=["explains softmax"],
                       must_include=["softmax", "QK^T"], weak_signs=["it just picks the max"]))
    session.add(ReferenceAnchor(source_doc_id=src.id, concept_id=concept.id,
                                question="why scale by sqrt(d)?", reference_answer="variance",
                                key_points=["dot-product variance grows with d"]))
    a1 = Assessment(concept_id=concept.id, kind="self_explanation", prompt="explain",
                    response="...", verdict="partial", score=0.6, gaps=["no scaling"])
    session.add(a1)
    session.commit()
    a2 = Assessment(concept_id=concept.id, kind="self_explanation", prompt="explain",
                    score=0.8, baseline_assessment_id=a1.id, delta=0.2)
    session.add(a2)
    session.add(SRSCard(concept_id=concept.id, front="f", back="b", due_at=_now()))
    session.add(RecallPrompt(concept_id=concept.id, prompt="derive attention", due_at=_now()))
    session.commit()

    assert session.exec(select(Rubric)).one().must_include == ["softmax", "QK^T"]
    assert session.exec(select(ReferenceAnchor)).one().key_points
    got = session.exec(select(Assessment).where(Assessment.delta == 0.2)).one()
    assert got.baseline_assessment_id == a1.id
    assert session.exec(select(SRSCard)).one().ease == 2.5
    assert session.exec(select(SRSCard)).one().status == "proposed"
    assert session.exec(select(RecallPrompt)).one().status == "proposed"
    # estimate still works
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
    session.commit()
