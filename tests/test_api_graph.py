from datetime import datetime, timezone

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import Concept, ConceptEdge, Topic, Track


def _topic_graph(session):
    topic = Topic(title="Graph")
    other_topic = Topic(title="Outside")
    session.add_all([topic, other_topic])
    session.flush()
    track = Track(topic_id=topic.id, title="Graph")
    other_track = Track(topic_id=other_topic.id, title="Outside")
    session.add_all([track, other_track])
    session.flush()
    target = Concept(track_id=track.id, name="Target", is_load_bearing=True)
    direct = Concept(track_id=track.id, name="Direct")
    deep = Concept(track_id=track.id, name="Deep")
    outside = Concept(track_id=other_track.id, name="Outside")
    session.add_all([target, direct, deep, outside])
    session.flush()
    session.add_all(
        [
            ConceptEdge(
                src_concept_id=target.id,
                dst_concept_id=direct.id,
                kind="prerequisite",
                origin="researcher",
                weight=0.8,
            ),
            ConceptEdge(
                src_concept_id=direct.id,
                dst_concept_id=deep.id,
                kind="prerequisite",
                origin="researcher",
            ),
            ConceptEdge(
                src_concept_id=target.id,
                dst_concept_id=deep.id,
                kind="related",
                origin="learner",
                valid_until=datetime(2026, 8, 25, tzinfo=timezone.utc),
            ),
            ConceptEdge(
                src_concept_id=target.id,
                dst_concept_id=outside.id,
                kind="related",
                origin="learner",
            ),
        ]
    )
    session.commit()
    return topic, target, direct, deep


def test_topic_graph_returns_nodes_and_current_internal_edges(session):
    topic, target, direct, deep = _topic_graph(session)
    app.dependency_overrides[get_session] = lambda: session
    try:
        response = TestClient(app).get(f"/api/topics/{topic.id}/graph")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert [node["id"] for node in body["nodes"]] == [target.id, direct.id, deep.id]
    assert body["edges"] == [
        {
            "src": target.id,
            "dst": direct.id,
            "kind": "prerequisite",
            "weight": 0.8,
        },
        {
            "src": direct.id,
            "dst": deep.id,
            "kind": "prerequisite",
            "weight": 1.0,
        },
    ]


def test_concept_ancestors_respects_requested_depth(session):
    _topic, target, direct, deep = _topic_graph(session)
    app.dependency_overrides[get_session] = lambda: session
    try:
        one = TestClient(app).get(f"/api/concepts/{target.id}/ancestors?depth=1")
        two = TestClient(app).get(f"/api/concepts/{target.id}/ancestors?depth=2")
    finally:
        app.dependency_overrides.clear()

    assert one.status_code == 200
    assert one.json() == [[direct.id, 1]]
    assert two.status_code == 200
    assert two.json() == [[direct.id, 1], [deep.id, 2]]


def test_concept_neighbors_and_unknown_concept(session):
    _topic, target, direct, deep = _topic_graph(session)
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        neighbors = client.get(f"/api/concepts/{direct.id}/neighbors")
        missing_ancestors = client.get("/api/concepts/999999/ancestors?depth=2")
        missing_neighbors = client.get("/api/concepts/999999/neighbors")
    finally:
        app.dependency_overrides.clear()

    assert neighbors.status_code == 200
    assert neighbors.json() == [target.id, deep.id]
    assert missing_ancestors.status_code == 404
    assert missing_neighbors.status_code == 404
