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


# --- The grade requires evidence the Assessor actually graded ------------------------------
# The stored estimate is a grade only when the concept has at least one assessment of a kind
# whose engine writes the estimate (assess.GRADING_KINDS). Everything else (teaching,
# productive failure, the ship review) leaves the curriculum's prior in place, and a prior
# is not a grade.


def test_artifact_only_history_has_no_grade(client, session):
    concept = _concept(session, "high")  # the curriculum's prior
    session.add(Assessment(concept_id=concept.id, kind="artifact_review", prompt="Ship: x",
                           score=0.9))
    session.commit()
    assert _history(client, concept.id)[0]["estimate_level"] is None


def test_artifact_teach_and_productive_failure_together_have_no_grade(client, session):
    concept = _concept(session, "high")
    for kind in ("artifact_review", "teach", "productive_failure"):
        session.add(Assessment(concept_id=concept.id, kind=kind, prompt="p", score=0.9))
    session.commit()
    assert all(r["estimate_level"] is None for r in _history(client, concept.id))


@pytest.mark.parametrize(
    "kind", ["self_explanation", "calibration", "source_quiz", "recall", "roleplay",
             "paper_probe"])
def test_one_graded_kind_makes_the_stored_estimate_the_grade(client, session, kind):
    concept = _concept(session, "medium")
    session.add(Assessment(concept_id=concept.id, kind=kind, prompt="p", score=0.6))
    session.add(Assessment(concept_id=concept.id, kind="artifact_review", prompt="p",
                           score=0.9))
    session.commit()
    rows = _history(client, concept.id)
    assert rows[0]["kind"] == "artifact_review"
    assert rows[0]["estimate_level"] == "medium"


def test_an_unknown_kind_is_not_evidence_of_a_grade(client, session):
    concept = _concept(session, "high")
    session.add(Assessment(concept_id=concept.id, kind="mystery", prompt="p", score=0.9))
    session.commit()
    assert _history(client, concept.id)[0]["estimate_level"] is None


def test_a_curriculum_seeded_concept_with_no_assessments_has_no_grade(client, session):
    # The real seeding path: generate_track writes KnowledgeEstimate(level="high") per concept.
    from adaptive_academy.engine.assess import graded_concept_ids

    concept = _concept(session, "high")
    assert _history(client, concept.id) == []
    assert graded_concept_ids(session, [concept.id]) == set()


def test_grading_kinds_are_exactly_the_kinds_that_write_the_estimate():
    from adaptive_academy.engine.assess import GRADING_KINDS

    assert GRADING_KINDS == {"self_explanation", "calibration", "source_quiz", "recall",
                             "roleplay", "paper_probe"}
    assert not GRADING_KINDS & {"teach", "productive_failure", "artifact_review"}
