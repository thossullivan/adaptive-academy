"""Seed for the README screenshot run (`npm run screenshots`), used instead of the e2e seed.

The db starts empty apart from this; the spec then adds the demo topic through the real
`POST /api/demo`, so every page shows the same data a keyless user sees after "Explore a demo
topic".

The demo topic records no model calls (it is built without an LLM), so the Usage page would be
empty. The rows below stand in for about ten weeks of use on claude-sonnet-5-5 (with the cheap
jobs on claude-haiku-5-5 and one curriculum on claude-opus-5-5): study sessions most days, and
a research run plus a curriculum every few weeks. The token counts are illustrative, sized from
measured live calls (2026-10-19: a research angle with 2 web searches was $0.081, a curriculum
track $0.028, a two-step tutor turn about $0.012). Costs come from the app's own price table.

Each call has an outcome, as an API-key call records one (research searches record none), with
a few of the problems the scorecard counts. The grade-check and tutor-guard events use the
detail format their real emitters write (engine/output_checks.summarize, engine/grade_gate.py,
engine/solution_guard.py), so the scorecard reads them the same way. These events belong to no
topic: the screenshot db has no topic of its own (the empty home page must stay empty), and
outside the scorecard nothing lists events without one.

"Cost per grade" stays empty on purpose: it divides by grades written outside the demo topic,
and this db has none.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from adaptive_academy.llm.pricing import cost_usd
from adaptive_academy.llm.usage import window_starts
from adaptive_academy.models import AgentEvent, LLMUsage

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"
OPUS = "claude-opus-5-5"


@dataclass(frozen=True)
class Call:
    feature: str
    operation: str
    input_tokens: int
    output_tokens: int
    model: str = SONNET
    cache_read: int = 0
    searches: int = 0
    outcome: str | None = "ok"


def tutor_turn(cache_read: int, outcome: str = "ok") -> list[Call]:
    """A two-step tutor turn: the reply, then the guard's check of it."""
    return [
        Call("tutor", "complete", 2_400, 320, cache_read=cache_read, outcome=outcome),
        Call("tutor", "complete_json", 1_900, 90),
    ]


def tutor_session(turns: int, cut_off_turn: int | None = None) -> list[Call]:
    calls: list[Call] = []
    for turn in range(turns):
        outcome = "cut_off" if turn == cut_off_turn else "ok"
        calls += tutor_turn(cache_read=1_500 * turn, outcome=outcome)
    return calls


GRADE = Call("assess", "complete", 3_600, 650)
RECALL = Call("decay", "complete", 2_700, 420)
TEACH = Call("teach", "complete", 3_200, 760)
CHALLENGE = [Call("productive_failure", "complete_json", 1_800, 520),
             Call("productive_failure", "complete", 3_100, 900)]
SCOUT = Call("scout", "complete_json", 6_000, 700, model=HAIKU)
ANCHORS = Call("anchors", "complete_json", 9_000, 2_200, model=HAIKU)
REMEDIATE = Call("remediate", "complete_json", 2_800, 600)
STORY = Call("story", "complete_json", 7_500, 1_400)


def research_run(angles: int, curriculum_model: str = SONNET,
                 invalid_curriculum: bool = False) -> list[Call]:
    """A new topic: research angles with web searches, then the curriculum."""
    calls = [Call("research", "research_search", 25_000, 1_100, searches=2, outcome=None)
             for _ in range(angles)]
    if invalid_curriculum:
        # The first structured answer was unusable; the one corrective retry fixed it.
        calls.append(Call("curriculum", "complete_json", 14_000, 5_200, model=curriculum_model,
                          outcome="invalid_output"))
    calls.append(Call("curriculum", "complete_json", 14_000, 5_600, model=curriculum_model))
    return calls


# Grade-check events per grading call: most pass first time, a few fail a check and pass on
# the one regeneration, one fails twice and is rejected.
PASS = "pass"
WARN_G8 = "pass WARN G8"
REGEN_G13 = "regen G13"
REGEN_J1 = "regen J1"
REJECT_G13 = "reject G13"

# (days ago, calls, grade outcomes in order of the grading calls, tutor guard events)
# "today" sessions are placed between local midnight and now, so they always land in today.
SESSIONS: list[tuple[float, list[Call], list[str], list[str]]] = [
    # today
    (0, tutor_session(4) + [GRADE, RECALL], [PASS, WARN_G8], ["checked"] * 4),
    (0, [TEACH, SCOUT], [PASS], []),
    # the last week
    (1, tutor_session(5) + [GRADE, GRADE, REMEDIATE], [PASS, REGEN_G13],
     ["checked", "checked", "blocked", "checked", "checked"]),
    (2, CHALLENGE + [RECALL, RECALL], [PASS, PASS, WARN_G8], []),
    (3, research_run(5) + [ANCHORS, SCOUT], [], []),
    (4, tutor_session(6, cut_off_turn=3) + [GRADE, TEACH], [PASS, PASS], ["checked"] * 6),
    (5, [GRADE, GRADE, RECALL, STORY], [WARN_G8, PASS, PASS], []),
    (6, tutor_session(3) + [GRADE], [REJECT_G13], ["checked", "unavailable", "checked"]),
    # the rest of the month
    (8, tutor_session(5) + [GRADE, RECALL], [PASS, PASS], ["checked"] * 5),
    (10, CHALLENGE + [TEACH, GRADE], [PASS, PASS, REGEN_J1], []),
    (12, tutor_session(4) + [GRADE, GRADE], [PASS, WARN_G8], ["checked", "blocked", "checked", "checked"]),
    (15, research_run(6, curriculum_model=OPUS, invalid_curriculum=True) + [ANCHORS], [], []),
    (17, tutor_session(6) + [RECALL, RECALL, GRADE], [PASS, PASS, PASS], ["checked"] * 6),
    (20, [GRADE, GRADE, TEACH, REMEDIATE, SCOUT], [PASS, REGEN_G13, PASS], []),
    (23, tutor_session(5) + CHALLENGE, [PASS], ["checked"] * 5),
    (26, [GRADE, RECALL, STORY], [PASS, PASS], []),
    (29, tutor_session(4) + [GRADE], [WARN_G8], ["checked"] * 4),
    # earlier
    (34, research_run(5) + [ANCHORS, SCOUT], [], []),
    (38, tutor_session(6) + [GRADE, GRADE, TEACH], [PASS, PASS, PASS], ["checked"] * 6),
    (43, CHALLENGE + [RECALL, GRADE, REMEDIATE], [PASS, PASS, REGEN_G13], []),
    (49, tutor_session(5) + [GRADE, RECALL], [PASS, PASS], ["checked", "blocked", "checked", "checked", "checked"]),
    (55, research_run(4, invalid_curriculum=True) + [ANCHORS], [], []),
    (62, tutor_session(4) + [GRADE, TEACH, STORY], [PASS, WARN_G8], ["checked"] * 4),
    (70, [GRADE, GRADE, RECALL, SCOUT], [PASS, PASS, PASS], []),
]

GRADING_FEATURES = {"assess", "decay", "teach", "productive_failure"}
RUBRIC = {"assess": "grade", "decay": "grade", "teach": "teach", "productive_failure": "consolidate"}


def _grade_events(rubric: str, outcome: str) -> list[tuple[str, str]]:
    if outcome in (PASS, WARN_G8):
        return [("grade:check", f"{rubric} attempt=1 {outcome}")]
    rule = outcome.split()[1]
    first = [("grade:check", f"{rubric} attempt=1 fail FAIL {rule}"),
             ("grade:regenerated", f"{rubric} after FAIL {rule}")]
    if outcome.startswith("regen"):
        return [*first, ("grade:check", f"{rubric} attempt=2 pass")]
    return [*first, ("grade:check", f"{rubric} attempt=2 fail FAIL {rule}"),
            ("grade:rejected", f"{rubric} rejected after 2 attempts: FAIL {rule}; nothing recorded")]


def _guard_events(kind: str) -> list[tuple[str, str]]:
    checked = ("guard:solution_checked", "source=model gives_away=false")
    if kind == "blocked":
        return [("guard:solution_checked", "source=model gives_away=true"),
                ("guard:solution_blocked", "source=model"),
                ("guard:solution_regenerated",
                 "draft withheld; asked the tutor for a question or hint instead")]
    if kind == "unavailable":
        return [("guard:unavailable", "overloaded: model check failed, screen used"),
                ("guard:solution_checked", "source=screen gives_away=false")]
    return [checked]


def _session_start(now: datetime, days_ago: float, index: int) -> datetime:
    if days_ago == 0:
        midnight = window_starts(now)["today"]
        assert midnight is not None
        # Spread today's sessions over the part of the day that has passed.
        return midnight + (now - midnight) * (0.25 + 0.35 * index)
    # Evenings, a little later each session, well clear of the rolling window edges.
    return now - timedelta(days=days_ago) + timedelta(minutes=17 * index)


def seed(session: Session, now: datetime | None = None) -> tuple[int, int]:
    """Write the usage rows and quality events. Returns (usage rows, events)."""
    now = now or datetime.now(timezone.utc)
    rows = events = 0
    today_index = 0
    for days_ago, calls, grades, guard in SESSIONS:
        start = _session_start(now, days_ago, today_index)
        if days_ago == 0:
            today_index += 1
        # 40 seconds between calls, closer together when that would run past now.
        span = min(timedelta(seconds=40), (now - start) / (2 * len(calls) + 2))
        grade_iter = iter(grades)
        for i, call in enumerate(calls):
            when = start + span * i
            session.add(LLMUsage(
                created_at=when, backend="anthropic", model=call.model,
                role="copy" if call.model == HAIKU else "reasoning",
                operation=call.operation, feature=call.feature,
                input_tokens=call.input_tokens, output_tokens=call.output_tokens,
                cache_read_input_tokens=call.cache_read,
                web_search_requests=call.searches, outcome=call.outcome,
                cost_usd=cost_usd(call.model, input_tokens=call.input_tokens,
                                  output_tokens=call.output_tokens,
                                  cache_read_input_tokens=call.cache_read,
                                  web_search_requests=call.searches),
            ))
            rows += 1
            if call.feature in GRADING_FEATURES and call.operation == "complete":
                outcome = next(grade_iter, None)
                assert outcome is not None, f"day {days_ago}: a grade with no outcome"
                for kind, detail in _grade_events(RUBRIC[call.feature], outcome):
                    session.add(AgentEvent(kind=kind, detail=detail, created_at=when))
                    events += 1
        assert next(grade_iter, None) is None, f"day {days_ago}: more grade outcomes than grades"
        for j, kind in enumerate(guard):
            for event_kind, detail in _guard_events(kind):
                session.add(AgentEvent(kind=event_kind, detail=detail,
                                       created_at=start + span * (2 * j + 1)))
                events += 1
    session.commit()
    return rows, events


if __name__ == "__main__":
    from adaptive_academy.db import engine

    with Session(engine) as db:
        n_rows, n_events = seed(db)
    print(f"screenshot seed: {n_rows} usage rows, {n_events} quality events")
