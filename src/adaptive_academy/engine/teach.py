"""Teach-It — explain to an audience, graded (§4 of the evidence base).

Learning-by-teaching (the protégé effect) is the highest-leverage generative strategy: it
forces select/organize/integrate, and the *explaining* + *interacting* parts drive durable
gains. The learner writes a public-facing explanation under a teaching expectancy; we grade it
as an authentic artifact — would a real audience actually learn from this?
"""

import json
from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Assessment, Concept


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def _as_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


_TEACH_SYSTEM = (
    "You evaluate a learner's PUBLIC EXPLANATION of a concept (learning-by-teaching / the "
    "protégé effect). Grade it as if a real, smart-but-uninformed audience must actually learn "
    "from it: clarity, correctness, completeness, and whether the reader would genuinely "
    "understand the mechanism (not just the vocabulary). Be honest — reward real teaching, flag "
    "hand-waving and borrowed jargon. Respond with ONLY a JSON object: "
    '{"score": number 0..1, "feedback": str (1-2 sentences, direct), "strengths": [str], '
    '"gaps": [str, what a reader would still be confused about]}. No prose outside the JSON.'
)


@dataclass
class TeachResult:
    assessment: Assessment
    score: float
    feedback: str
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


def parse_teaching_json(text: str) -> tuple[float, str, list[str], list[str]]:
    d = json.loads(_strip_fences(text))
    return (
        max(0.0, min(1.0, _as_float(d.get("score"), 0.0))),
        str(d.get("feedback", "")).strip(),
        [str(s).strip() for s in (d.get("strengths", []) or []) if str(s).strip()],
        [str(g).strip() for g in (d.get("gaps", []) or []) if str(g).strip()],
    )


def grade_teaching(session: Session, concept: Concept, explanation: str, *, llm: LLMClient) -> TeachResult:
    """Grade a public explanation under a teaching expectancy; persist as a teach assessment."""
    user = f"CONCEPT: {concept.name}\n\nLEARNER'S PUBLIC EXPLANATION:\n{explanation or '(empty)'}"
    resp = llm.complete(system=_TEACH_SYSTEM, messages=[{"role": "user", "content": user}], tools=[])
    score, feedback, strengths, gaps = parse_teaching_json(resp.text)

    assessment = Assessment(
        concept_id=concept.id,
        kind="teach",
        prompt=f"Teach: {concept.name}",
        response=explanation,
        verdict=feedback,
        score=score,
        gaps=gaps,
    )
    session.add(assessment)
    session.commit()
    session.refresh(assessment)
    return TeachResult(
        assessment=assessment, score=score, feedback=feedback, strengths=strengths, gaps=gaps
    )


def has_taught(session: Session, concept_id: int) -> bool:
    """Whether the learner has a graded teaching artifact for this concept."""
    return session.exec(
        select(Assessment).where(
            Assessment.concept_id == concept_id, Assessment.kind == "teach"
        )
    ).first() is not None
