# tests/test_retention_sm2.py
from adaptive_academy.engine.retention import sm2_schedule


def test_good_progression():
    assert sm2_schedule(2.5, 0, 0, "good") == (2.5, 1, 1)
    assert sm2_schedule(2.5, 1, 1, "good") == (2.5, 6, 2)
    ease, interval, reps = sm2_schedule(2.5, 6, 2, "good")
    assert reps == 3 and interval == 15  # round(6 * 2.5)


def test_again_resets_and_lowers_ease():
    ease, interval, reps = sm2_schedule(2.5, 6, 2, "again")
    assert (interval, reps) == (1, 0) and ease < 2.5


def test_hard_advances_but_lowers_ease():
    ease, interval, reps = sm2_schedule(2.5, 1, 1, "hard")
    assert reps == 2 and interval == 6 and ease < 2.5


def test_ease_floor():
    ease, _, _ = sm2_schedule(1.3, 6, 2, "again")
    assert ease == 1.3
