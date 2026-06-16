from adaptive_academy.engine.anchors import AnchorGenError, generate_anchors
from adaptive_academy.llm.anchor_types import RawAnchor
from adaptive_academy.llm.scripted_anchor import ScriptedAnchorClient
from adaptive_academy.models import (
    Concept, ReferenceAnchor, SourceDoc, Topic, TopicFoundation, Track,
)
from sqlmodel import select


def _seed(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["softmax", "self-attention"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    session.add(Concept(track_id=track.id, name="softmax"))
    s1 = SourceDoc(topic_id=topic.id, title="s1", url="u1", status="accepted")
    s2 = SourceDoc(topic_id=topic.id, title="s2", url="u2", status="accepted")
    s3 = SourceDoc(topic_id=topic.id, title="s3", url="u3", status="proposed")
    session.add(s1)
    session.add(s2)
    session.add(s3)
    session.commit()
    return topic, track, s1, s2


def test_generate_fans_out_over_accepted_sources(session):
    topic, track, s1, s2 = _seed(session)
    client = ScriptedAnchorClient({
        s1.id: [RawAnchor(question="why softmax?", reference_answer="ra",
                          key_points=["subtract max"], concept_name="softmax")],
        s2.id: [RawAnchor(question="what is attention?", reference_answer="rb",
                          key_points=["QK^T"], concept_name="unmatched")],
    })
    res = generate_anchors(session, topic, anchor_client=client)
    assert len(res.anchors) == 2
    assert sorted(client.calls) == sorted([s1.id, s2.id])
    rows = session.exec(select(ReferenceAnchor)).all()
    by_q = {r.question: r for r in rows}
    assert by_q["why softmax?"].concept_id is not None
    assert by_q["what is attention?"].concept_id is None
    assert {e.kind for e in res.events} >= {"anchors:plan", "anchors:done"}


def test_generate_is_idempotent(session):
    topic, track, s1, s2 = _seed(session)
    client = ScriptedAnchorClient({
        s1.id: [RawAnchor(question="why softmax?", concept_name="softmax")],
        s2.id: [],
    })
    generate_anchors(session, topic, anchor_client=client)
    res2 = generate_anchors(session, topic, anchor_client=client)
    assert res2.anchors == []
    assert len(session.exec(select(ReferenceAnchor)).all()) == 1


def test_generate_preserves_source_order_under_concurrency(session):
    # Lock the fan-out invariant: with max_workers > 1, results are collected in
    # SOURCE (rank) order, not completion order — and no Session is touched in a worker.
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["c"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    srcs = []
    for i in range(5):
        s = SourceDoc(topic_id=topic.id, title=f"s{i}", url=f"u{i}",
                      status="accepted", rank=i)
        session.add(s)
        srcs.append(s)
    session.commit()
    client = ScriptedAnchorClient({
        s.id: [RawAnchor(question=f"q{i}")] for i, s in enumerate(srcs)})
    res = generate_anchors(session, topic, anchor_client=client, max_workers=5)
    # Persisted/returned anchors follow source rank order q0..q4.
    assert [a.question for a in res.anchors] == [f"q{i}" for i in range(5)]


def test_generate_raises_without_accepted_sources(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    client = ScriptedAnchorClient({})
    try:
        generate_anchors(session, topic, anchor_client=client)
        assert False, "expected AnchorGenError"
    except AnchorGenError:
        pass
