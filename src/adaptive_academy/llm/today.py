"""Today's date for every system prompt a real model client sends.

A model with no date in its context guesses one (a sibling project's tutor once wrote "Today
is Thursday" on a Friday). Each client appends `today_line()` at the END of its system text,
after everything stable, so the stable part stays a cacheable prefix (llm/anthropic_client.py
puts its cache breakpoint before this line).

"Today" is the server's local calendar day, like the daily spending limit (llm/usage.py): UTC
in the Docker image unless TZ is set. Tests patch `local_now`.
"""

from datetime import datetime

# Spelled out rather than strftime("%A"), which follows the process locale.
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def local_now() -> datetime:
    """The current moment in the server's local timezone. Patched in tests."""
    return datetime.now().astimezone()


def today_line(now: datetime | None = None) -> str:
    """One short line: the local date in ISO form plus its weekday."""
    day = (now if now is not None else local_now()).date()
    return f"Today's date is {day.isoformat()} ({_WEEKDAYS[day.weekday()]})."


def with_today(system: str) -> str:
    """`system` with today's date line appended at the end (string-only callers)."""
    return f"{system}\n\n{today_line()}"
