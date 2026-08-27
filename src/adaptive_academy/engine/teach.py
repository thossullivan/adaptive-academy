"""Teach-It — explain to an audience, graded (§4 of the evidence base).

Learning-by-teaching (the protégé effect) is the highest-leverage generative strategy: it
forces select/organize/integrate, and the *explaining* + *interacting* parts drive durable
gains. The learner writes a public-facing explanation under a teaching expectancy; we grade it
as an authentic artifact — would a real audience actually learn from this?
"""

import json
from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.engine.memory import index_assessment, topic_id_for_concept
from adaptive_academy.engine.trace import trace_prompt
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Assessment, Concept
from adaptive_academy.prompts import TEACH
from adaptive_academy.engine.untrusted import escape_markers



def _as_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class TeachResult:
    assessment: Assessment
    score: float
    feedback: str
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


def parse_teaching_json(text: str) -> tuple[float, str, list[str], list[str]]:
    d = json.loads(extract_json(text))
    return (
        max(0.0, min(1.0, _as_float(d.get("score"), 0.0))),
        str(d.get("feedback", "")).strip(),
        [str(s).strip() for s in (d.get("strengths", []) or []) if str(s).strip()],
        [str(g).strip() for g in (d.get("gaps", []) or []) if str(g).strip()],
    )


def grade_teaching(
    session: Session,
    concept: Concept,
    explanation: str,
    *,
    llm: LLMClient,
    retriever: Retriever | None = None,
) -> TeachResult:
    """Grade a public explanation under a teaching expectancy; persist as a teach assessment."""
    user = (f"CONCEPT: {concept.name}\n\n<<<TEACHING>>>\n"
            f"{escape_markers(explanation or '(empty)')}\n<<<END_TEACHING>>>")
    topic_id = topic_id_for_concept(session, concept.id)
    trace_prompt(session, TEACH, topic_id=topic_id)
    resp = llm.complete(system=TEACH, messages=[{"role": "user", "content": user}], tools=[])
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
    session.flush()
    index_assessment(session, assessment, topic_id=topic_id, retriever=retriever)
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
