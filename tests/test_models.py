from adaptive_academy.models import (
    Concept,
    Conversation,
    KnowledgeEstimate,
    Message,
    Topic,
    Track,
)


def test_topic_track_concept_estimate_roundtrip(session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()

    track = Track(topic_id=topic.id, title="Core track")
    session.add(track)
    session.commit()

    concept = Concept(track_id=track.id, name="self-attention", is_load_bearing=True)
    session.add(concept)
    session.commit()

    est = KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6)
    session.add(est)
    session.commit()

    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    session.add(Message(conversation_id=convo.id, role="user", content="hi"))
    session.commit()

    assert concept.estimate.level == "high"
    assert convo.messages[0].content == "hi"
    assert convo.attempt_logged is False
