"""The competence 'grade' in the assessment history is the concept's STORED KnowledgeEstimate
(written by the Assessor), carried on the newest row only — never recomputed per row from
whatever that row's score was."""

import pytest
from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import Assessment, Concept, KnowledgeEstimate, Topic, Track


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _concept(session, level: str | None) -> Concept:
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="c")
    session.add(concept)
    session.commit()
    if level is not None:
        session.add(KnowledgeEstimate(concept_id=concept.id, level=level, confidence=0.8))
        session.commit()
    return concept


def _history(client, concept_id):
    return client.get(f"/api/concepts/{concept_id}/assessments").json()


def test_newest_row_carries_the_stored_estimate_not_its_own_score(client, session):
    concept = _concept(session, "high")
    session.add(Assessment(concept_id=concept.id, kind="self_explanation", prompt="p",
                           score=0.9))
    session.add(Assessment(concept_id=concept.id, kind="recall", prompt="p", score=0.2))
    session.commit()
    rows = _history(client, concept.id)
    assert [r["kind"] for r in rows] == ["recall", "self_explanation"]  # newest first
    # A low-scoring newest recall does not downgrade the stored grade...
    assert rows[0]["estimate_level"] == "high"
    # ...and older rows carry no grade of their own.
    assert rows[1]["estimate_level"] is None


def test_no_stored_estimate_means_no_grade(client, session):
    concept = _concept(session, None)
    session.add(Assessment(concept_id=concept.id, kind="self_explanation", prompt="p",
                           score=0.9))
    session.commit()
    assert _history(client, concept.id)[0]["estimate_level"] is None


@pytest.mark.parametrize("kind", ["teach", "productive_failure"])
def test_a_prior_is_not_a_grade_when_nothing_has_graded_the_concept(client, session, kind):
    # The curriculum seeds every concept with a prior estimate; teaching or a productive-
    # failure attempt never write the estimate, so on their own they leave it ungraded.
    concept = _concept(session, "high")
    session.add(Assessment(concept_id=concept.id, kind=kind, prompt="p", score=0.9))
    session.commit()
    assert _history(client, concept.id)[0]["estimate_level"] is None


def test_empty_history(client, session):
    concept = _concept(session, "high")
    assert _history(client, concept.id) == []
