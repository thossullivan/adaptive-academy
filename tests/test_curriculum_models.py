from sqlmodel import Session, select

from adaptive_academy.models import (
    Deliverable, Item, Phase, Sidebar, Topic, Track,
)


def test_track_phase_item_deliverable_sidebar(session: Session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Core track", overview="intro prose")
    session.add(track)
    session.commit()

    phase = Phase(track_id=track.id, title="Build a GPT", position=0,
                  est_hours="Weeks 2-5", flags=["optional"])
    session.add(phase)
    session.commit()
    session.add(Item(phase_id=phase.id, text="Karpathy video", type="watch",
                     position=0, concept_refs=["self-attention"]))
    session.add(Deliverable(phase_id=phase.id, kind="repo", text="nanoGPT repo",
                            acceptance_criteria=["trains", "writeup"]))
    session.add(Sidebar(track_id=track.id, kind="math_refresh",
                        title="Math foundations", body="linear algebra", position=0))
    session.commit()

    session.refresh(track)
    session.refresh(phase)
    assert track.overview == "intro prose"
    assert track.phases[0].title == "Build a GPT"
    assert track.phases[0].flags == ["optional"]
    assert track.phases[0].items[0].concept_refs == ["self-attention"]
    assert track.phases[0].deliverable.acceptance_criteria == ["trains", "writeup"]
    assert track.sidebars[0].kind == "math_refresh"
    item = session.exec(select(Item)).one()
    assert item.status == "todo" and item.type == "watch"
