import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import Assessment, Concept, Topic, Track


def _seed(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax", is_load_bearing=True)
    session.add(concept)
    session.commit()
    a = Assessment(concept_id=concept.id, kind="self_explanation", prompt="p", score=0.4,
                   gaps=["omitted required element: subtract the max"])
    session.add(a)
    session.commit()
    return topic.id, concept.id, a.id


def test_propose_list_review_grade(session):
    app.dependency_overrides[get_session] = lambda: session
    payload = json.dumps({"cards": [{"front": "f", "back": "b"}],
                          "prompts": ["recall X"]})
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([LLMResponse(text=payload)])
    topic_id, cid, aid = _seed(session)
    client = TestClient(app)

    pr = client.post(f"/api/concepts/{cid}/retention/propose", json={"from_assessment_id": aid})
    assert pr.status_code == 200 and len(pr.json()["cards"]) == 1
    card_id = pr.json()["cards"][0]["id"]

    lst = client.get(f"/api/topics/{topic_id}/retention")
    assert lst.status_code == 200 and len(lst.json()["cards"]) == 1

    rev = client.post(f"/api/retention/cards/{card_id}/review", json={"status": "active"})
    assert rev.status_code == 200 and rev.json()["status"] == "active"
    assert client.post(f"/api/retention/cards/{card_id}/review",
                       json={"status": "bogus"}).status_code == 422

    gr = client.post(f"/api/retention/cards/{card_id}/grade", json={"result": "good"})
    assert gr.status_code == 200 and gr.json()["reps"] == 1
    assert client.post(f"/api/retention/cards/{card_id}/grade",
                       json={"result": "bogus"}).status_code == 422

    # The graded card was scheduled into the future, so it is no longer "due now".
    due = client.get(f"/api/topics/{topic_id}/retention?due=true")
    assert due.status_code == 200 and len(due.json()["cards"]) == 0
    app.dependency_overrides.clear()


def test_propose_with_no_prior_assessment_400s(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([])  # never called (400 first)
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="bare")
    session.add(concept)
    session.commit()
    client = TestClient(app)
    r = client.post(f"/api/concepts/{concept.id}/retention/propose", json={})
    assert r.status_code == 400
    app.dependency_overrides.clear()


def test_due_now_surfaces_an_overdue_active_card(session):
    from datetime import datetime, timezone

    from adaptive_academy.models import SRSCard
    app.dependency_overrides[get_session] = lambda: session
    topic_id, cid, _ = _seed(session)
    session.add(SRSCard(concept_id=cid, front="f", back="b", status="active",
                        due_at=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    session.add(SRSCard(concept_id=cid, front="later", back="b", status="active",
                        due_at=datetime(2999, 1, 1, tzinfo=timezone.utc)))
    session.commit()
    client = TestClient(app)
    due = client.get(f"/api/topics/{topic_id}/retention?due=true").json()
    assert len(due["cards"]) == 1 and due["cards"][0]["front"] == "f"
    app.dependency_overrides.clear()
