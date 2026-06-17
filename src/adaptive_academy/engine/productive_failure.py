"""Productive Failure — generate before instruction (§8.5/§6 of the evidence base).

Withholding answers (the Tutor's attempt-gate) is *necessary but not sufficient*; it must be
paired with mechanisms that force generative effort. Here the learner grapples with a NOVEL
problem and commits an attempt BEFORE any canonical method is shown, then consolidates. The
grade rewards the **quality of the generative struggle**, not whether the final answer was
right — failing productively is the point.
"""

import json
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Assessment, Concept, TopicFoundation, Track


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


_GENERATE_SYSTEM = (
    "You design a PRODUCTIVE FAILURE problem for an advanced learner. Produce ONE novel, "
    "concrete problem that requires applying the concept but DO NOT reveal the method, the "
    "approach, or the answer. It should be solvable with real effort (desirable difficulty) "
    "and force the learner to GENERATE an approach from scratch. Respond with ONLY a JSON "
    'object: {"problem": str}. No prose outside the JSON.'
)

_CONSOLIDATE_SYSTEM = (
    "You evaluate a learner's GENERATIVE ATTEMPT at a problem they tackled BEFORE any "
    "instruction (productive failure). Grade the QUALITY OF REASONING and the productive "
    "structure of the attempt — NOT whether the final answer is correct; failing productively "
    "is expected and valuable. Reward identifying the right sub-problems, sound intuitions, and "
    "honest dead-ends. Then teach the canonical approach. Respond with ONLY a JSON object: "
    '{"canonical": str (the worked approach), "feedback": str (what the reasoning got right '
    "and where it broke, 2-3 sentences), \"score\": number 0..1 (quality of generative "
    'effort)}. No prose outside the JSON.'
)


@dataclass
class ConsolidateResult:
    assessment: Assessment
    canonical: str
    feedback: str
    score: float


def _topic_id_for(session: Session, concept: Concept) -> int:
    return session.get(Track, concept.track_id).topic_id


def build_generate_prompt(concept_name: str, foundation: TopicFoundation | None) -> tuple[str, str]:
    lines = [f"CONCEPT: {concept_name}"]
    if foundation and foundation.overview:
        lines.append(f"CONTEXT: {foundation.overview}")
    return _GENERATE_SYSTEM, "\n".join(lines)


def parse_problem_json(text: str) -> str:
    d = json.loads(_strip_fences(text))
    return str(d.get("problem", "")).strip()


def parse_consolidation_json(text: str) -> tuple[str, str, float]:
    d = json.loads(_strip_fences(text))
    return (
        str(d.get("canonical", "")).strip(),
        str(d.get("feedback", "")).strip(),
        max(0.0, min(1.0, _as_float(d.get("score"), 0.0))),
    )


def generate_challenge(session: Session, concept: Concept, *, llm: LLMClient) -> str:
    """Generate a novel, method-withholding problem for the concept."""
    topic_id = _topic_id_for(session, concept)
    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)
    ).first()
    system, user = build_generate_prompt(concept.name, foundation)
    resp = llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[])
    return parse_problem_json(resp.text)


def consolidate(
    session: Session, concept: Concept, problem: str, attempt: str, *, llm: LLMClient
) -> ConsolidateResult:
    """Grade the generative attempt and teach the canonical approach; persist the record."""
    user = f"CONCEPT: {concept.name}\n\nPROBLEM:\n{problem}\n\nLEARNER ATTEMPT:\n{attempt or '(none)'}"
    resp = llm.complete(
        system=_CONSOLIDATE_SYSTEM, messages=[{"role": "user", "content": user}], tools=[]
    )
    canonical, feedback, score = parse_consolidation_json(resp.text)

    assessment = Assessment(
        concept_id=concept.id,
        kind="productive_failure",
        prompt=problem,
        response=attempt,
        verdict=feedback,
        score=score,
        gaps=[],
    )
    session.add(assessment)
    session.commit()
    session.refresh(assessment)
    return ConsolidateResult(
        assessment=assessment, canonical=canonical, feedback=feedback, score=score
    )
