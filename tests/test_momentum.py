from datetime import datetime, timedelta, timezone

from adaptive_academy.engine.momentum import classify, decayed_wind

NOW = datetime(2026, 6, 17, 12, 0, 0)


def test_decayed_wind_sums_half_life_weights():
    # one event now (weight 1.0) + one 3 days ago (weight 0.5) = 1.5
    times = [NOW, NOW - timedelta(days=3)]
    assert round(decayed_wind(times, NOW), 3) == 1.5


def test_decayed_wind_empty_is_zero():
    assert decayed_wind([], NOW) == 0.0


def test_decayed_wind_is_tz_robust():
    # Mixed aware/naive timestamps (in-memory ORM objects are aware; SQLite reads come
    # back naive) must not raise and must be treated as the same instant.
    aware = NOW.replace(tzinfo=timezone.utc)
    assert round(decayed_wind([aware], NOW), 3) == 1.0
    assert round(decayed_wind([NOW], aware), 3) == 1.0


def test_classify_states():
    assert classify(0.0, None) == "unsailed"         # never sailed (distinct from lapsed)
    assert classify(1.0, 12.0) == "becalmed"         # gone 12 days
    assert classify(1.0, 5.0) == "fading"            # gone 5 days
    assert classify(2.5, 0.0) == "cruising"          # rich + recent
    assert classify(1.0, 1.0) == "steady"            # recent, moderate


# --- Task 2: topic_wind + fleet (derived from the Assessment log) ---

from adaptive_academy.engine.momentum import fleet, topic_wind  # noqa: E402
from adaptive_academy.models import Assessment, Concept, Topic, Track  # noqa: E402


def _topic_with_concept(session, title):
    t = Topic(title=title)
    session.add(t)
    session.commit()
    session.refresh(t)
    tr = Track(topic_id=t.id, title="tr")
    session.add(tr)
    session.commit()
    session.refresh(tr)
    c = Concept(track_id=tr.id, name="C")
    session.add(c)
    session.commit()
    session.refresh(c)
    return t, c


def _assess(session, concept_id, kind, when):
    session.add(Assessment(concept_id=concept_id, kind=kind, prompt="", created_at=when))
    session.commit()


def test_topic_wind_counts_only_qualifying_assessments(session):
    t, c = _topic_with_concept(session, "Build LLMs")
    _assess(session, c.id, "teach", NOW)               # qualifies (teach-back)
    _assess(session, c.id, "not_a_real_kind", NOW)     # ignored (unknown kind)
    ws = topic_wind(session, t.id, now=NOW)
    assert ws.topic_title == "Build LLMs"
    assert round(ws.value, 3) == 1.0                   # only the one qualifying assessment
    assert ws.state == "steady"
    assert ws.days_since == 0.0


def test_topic_wind_counts_paper_probe_assessment(session):
    t, c = _topic_with_concept(session, "Probed topic")
    _assess(session, c.id, "paper_probe", NOW)          # qualifies (graded paper probe)
    ws = topic_wind(session, t.id, now=NOW)
    assert round(ws.value, 3) == 1.0
    assert ws.state == "steady"
    assert ws.days_since == 0.0


def test_topic_wind_unsailed_when_no_assessments(session):
    t, _ = _topic_with_concept(session, "Quiet topic")
    ws = topic_wind(session, t.id, now=NOW)
    assert ws.state == "unsailed" and ws.value == 0.0 and ws.last_sailed is None


def test_topic_wind_dedups_same_commit_ship(session):
    # An artifact ship writes one artifact_review per concept in one commit. The rows are
    # constructed in a loop, so default_factory=_now fires per row -> timestamps differ by
    # microseconds (NOT identical). That's still ONE real action -> one gust, not N. Use
    # realistic sub-second-apart timestamps so this actually guards the dedup.
    t, c = _topic_with_concept(session, "Ship day")
    c2 = Concept(track_id=c.track_id, name="C2")
    session.add(c2)
    session.commit()
    session.refresh(c2)
    _assess(session, c.id, "artifact_review", NOW)
    _assess(session, c2.id, "artifact_review", NOW + timedelta(microseconds=37))
    ws = topic_wind(session, t.id, now=NOW)
    assert round(ws.value, 3) == 1.0                   # collapsed to a single action


def test_fleet_sorts_attention_first(session):
    hot, hc = _topic_with_concept(session, "Hot")
    cold, cc = _topic_with_concept(session, "Cold")
    _assess(session, hc.id, "teach", NOW)                          # steady
    _assess(session, cc.id, "self_explanation", NOW - timedelta(days=12))  # becalmed
    order = [w.topic_title for w in fleet(session, now=NOW)]
    assert order[0] == "Cold"  # becalmed floats to the top


# --- Task 3: comeback_move (the C-shaped seam) ---

from adaptive_academy.engine.momentum import comeback_move  # noqa: E402
from adaptive_academy.models import Item, Phase  # noqa: E402


def test_comeback_move_none_when_healthy(session):
    t, c = _topic_with_concept(session, "Healthy")
    _assess(session, c.id, "teach", NOW)  # steady
    assert comeback_move(session, t.id, now=NOW) is None


def test_comeback_move_picks_next_undone_item_when_fading(session):
    t, c = _topic_with_concept(session, "Fading topic")
    _assess(session, c.id, "self_explanation", NOW - timedelta(days=5))  # fading
    phase = Phase(track_id=c.track_id, title="P1", position=0)
    session.add(phase)
    session.commit()
    session.refresh(phase)
    session.add(Item(phase_id=phase.id, text="done item", type="read", position=0, status="done"))
    session.add(Item(phase_id=phase.id, text="derive the gradient", type="write", position=1,
                     status="todo"))
    session.commit()
    move = comeback_move(session, t.id, now=NOW)
    assert move is not None
    assert move.label == "derive the gradient"
    assert move.href == f"/topics/{t.id}/track"


def test_comeback_move_falls_back_without_track(session):
    t = Topic(title="No track")
    session.add(t)
    session.commit()
    session.refresh(t)  # no track/assessments -> unsailed
    move = comeback_move(session, t.id, now=NOW)
    assert move is not None and move.kind == "self_explain"
    assert move.href == f"/topics/{t.id}/assess"


def test_comeback_move_fires_first_launch_for_unsailed_with_track(session):
    # A never-sailed topic that already has a curriculum gets a first-launch nudge toward the
    # next undone item (not suppressed, not the self-explain fallback).
    t, c = _topic_with_concept(session, "Charted but unsailed")
    phase = Phase(track_id=c.track_id, title="P1", position=0)
    session.add(phase)
    session.commit()
    session.refresh(phase)
    session.add(Item(phase_id=phase.id, text="read the attention paper", type="read",
                     position=0, status="todo"))
    session.commit()
    ws = topic_wind(session, t.id, now=NOW)
    assert ws.state == "unsailed"
    move = comeback_move(session, t.id, now=NOW)
    assert move is not None
    assert move.label == "read the attention paper"
    assert move.href == f"/topics/{t.id}/track"
