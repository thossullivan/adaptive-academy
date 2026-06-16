import json
from datetime import timedelta

from sqlmodel import Session

from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Assessment, Concept, RecallPrompt, SRSCard, _now

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


_RETENTION_SYSTEM = (
    "You propose a FEW high-quality, curated spaced-repetition cards and active-recall "
    "prompts for ONE load-bearing concept, targeting the learner's demonstrated gaps. "
    "Cards test understanding, not trivia. Respond with ONLY a JSON object: "
    '{"cards": [{"front": str, "back": str}], "prompts": [str, free-recall/Feynman '
    'prompts]}. At most 3 cards and 2 prompts. No prose outside the JSON.'
)


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def propose_retention(
    session: Session, concept: Concept, assessment: Assessment, *, llm: LLMClient,
) -> tuple[list[SRSCard], list[RecallPrompt]]:
    """Generate proposed (user-reviewable) cards + recall prompts from gaps (§2.6)."""
    user = (f"CONCEPT: {concept.name}\nDEMONSTRATED GAPS: "
            f"{'; '.join(assessment.gaps) or '(none)'}\nVERDICT: {assessment.verdict}")
    resp = llm.complete(system=_RETENTION_SYSTEM,
                        messages=[{"role": "user", "content": user}], tools=[])
    data = json.loads(_strip_fences(resp.text))
    cards: list[SRSCard] = []
    for c in (data.get("cards", []) or [])[:3]:
        card = SRSCard(concept_id=concept.id, front=str(c.get("front", "")),
                       back=str(c.get("back", "")), status="proposed", due_at=_now())
        session.add(card)
        cards.append(card)
    prompts: list[RecallPrompt] = []
    for p in (data.get("prompts", []) or [])[:2]:
        rp = RecallPrompt(concept_id=concept.id, prompt=str(p), status="proposed", due_at=_now())
        session.add(rp)
        prompts.append(rp)
    session.commit()
    for c in cards:
        session.refresh(c)
    for p in prompts:
        session.refresh(p)
    return cards, prompts


def grade_card(session: Session, card: SRSCard, result: str) -> SRSCard:
    """Apply SM-2 to a due card and advance its due date."""
    card.ease, card.interval, card.reps = sm2_schedule(
        card.ease, card.interval, card.reps, result)
    due_at = _now() + timedelta(days=card.interval)
    card.due_at = due_at
    card.last_result = result
    session.add(card)
    session.commit()
    # NOTE: commit expires attributes; re-reading due_at from SQLite yields a
    # tz-naive datetime, which breaks aware/naive comparisons downstream. Restore
    # the tz-aware value we computed so callers keep a usable, aware due date.
    card.due_at = due_at
    return card
