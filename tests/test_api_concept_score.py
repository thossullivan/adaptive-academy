from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import Assessment, Concept, Topic, Track


def test_topic_concept_includes_last_assessment_score(session):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="c")
    session.add(concept)
    session.commit()
    session.add(Assessment(concept_id=concept.id, kind="self_explanation", prompt="p", score=0.42))
    session.commit()

    client = TestClient(app)
    body = client.get(f"/api/topics/{topic.id}").json()
    assert body["concepts"][0]["last_assessment_score"] == 0.42
    app.dependency_overrides.clear()
