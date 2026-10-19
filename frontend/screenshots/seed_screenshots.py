"""Seed for the README screenshot run (`npm run screenshots`), used instead of the e2e seed.

The db starts empty apart from this; the spec then adds the demo topic through the real
`POST /api/demo`, so every page shows the same data a keyless user sees after "Explore a demo
topic".

The demo topic records no model calls (it is built without an LLM), so the Usage page would be
empty. The rows below stand in for one measured live session on claude-sonnet-5-5
(2026-10-19): one research angle with 2 web searches ($0.081), one curriculum track ($0.028),
one scout ranking ($0.005) and two two-step tutor turns ($0.011 and $0.013). The dollar figures
are the measured ones; the token split of each call is back-solved from its cost at list price
and is illustrative. Costs are computed with the app's own price table, so they match exactly.
"""

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from adaptive_academy.db import engine
from adaptive_academy.llm.pricing import cost_usd
from adaptive_academy.models import LLMUsage

MODEL = "claude-sonnet-5-5"

# (minutes ago, feature, operation, input tokens, output tokens, web searches)
CALLS = [
    (95, "research", "research_search", 25_000, 1_100, 2),  # $0.081
    (80, "curriculum", "complete_json", 4_000, 2_000, 0),  # $0.028
    (70, "scout", "complete_json", 1_500, 200, 0),  # $0.005
    (40, "tutor", "complete", 2_400, 120, 0),  # turn 1, step 1
    (40, "tutor", "complete", 2_000, 100, 0),  # turn 1, step 2: $0.011 for the turn
    (25, "tutor", "complete", 2_600, 180, 0),  # turn 2, step 1
    (25, "tutor", "complete", 2_500, 100, 0),  # turn 2, step 2: $0.013 for the turn
]


def seed() -> None:
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        for minutes, feature, operation, inp, out, searches in CALLS:
            session.add(LLMUsage(
                created_at=now - timedelta(minutes=minutes),
                backend="anthropic", model=MODEL, role="reasoning", operation=operation,
                feature=feature, input_tokens=inp, output_tokens=out,
                web_search_requests=searches,
                cost_usd=cost_usd(MODEL, input_tokens=inp, output_tokens=out,
                                  web_search_requests=searches),
            ))
        session.commit()
    print(f"screenshot seed: {len(CALLS)} usage rows")


if __name__ == "__main__":
    seed()
