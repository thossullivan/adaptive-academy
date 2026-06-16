_QUALITY = {"again": 2, "hard": 3, "good": 4, "easy": 5}


def sm2_schedule(ease: float, interval: int, reps: int, result: str) -> tuple[float, int, int]:
    """Pure SM-2 step. Returns the new (ease, interval_days, reps).

    A lapse (again, q<3) resets interval to 1 and reps to 0; the ease factor is
    adjusted by the standard SM-2 formula for every grade and floored at 1.3.
    """
    q = _QUALITY.get(result, 4)
    new_ease = max(1.3, ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
    if q < 3:
        return new_ease, 1, 0
    new_reps = reps + 1
    if new_reps == 1:
        new_interval = 1
    elif new_reps == 2:
        new_interval = 6
    else:
        new_interval = max(1, round(interval * new_ease))
    return new_ease, new_interval, new_reps
