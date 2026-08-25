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

from adaptive_academy.engine.memory import (
    content_hash,
    index_assessment,
    index_question,
    topic_id_for_concept,
)
from adaptive_academy.engine.trace import trace_prompt
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Assessment, Concept, KnowledgeEstimate, TopicFoundation
from adaptive_academy.prompts import PF_CONSOLIDATE, PF_GENERATE



def _as_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class ConsolidateResult:
    assessment: Assessment
    canonical: str
    feedback: str
    score: float


def build_generate_prompt(
    concept_name: str, foundation: TopicFoundation | None, level: str = "unknown"
) -> tuple[str, str]:
    lines = [f"CONCEPT: {concept_name}", f"LEARNER PRIOR-KNOWLEDGE LEVEL: {level}"]
    if foundation and foundation.overview:
        lines.append(f"CONTEXT: {foundation.overview}")
    return PF_GENERATE, "\n".join(lines)


def parse_problem_json(text: str) -> str:
    d = json.loads(extract_json(text))
    return str(d.get("problem", "")).strip()


def parse_consolidation_json(text: str) -> tuple[str, str, float]:
    d = json.loads(extract_json(text))
    return (
        str(d.get("canonical", "")).strip(),
        str(d.get("feedback", "")).strip(),
        max(0.0, min(1.0, _as_float(d.get("score"), 0.0))),
    )


def generate_challenge(session: Session, concept: Concept, *, llm: LLMClient) -> str:
    """Generate a novel, method-withholding problem for the concept."""
    topic_id = topic_id_for_concept(session, concept.id)
    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)
    ).first()
    est = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept.id)
    ).first()
    system, user = build_generate_prompt(concept.name, foundation, est.level if est else "unknown")
    trace_prompt(session, PF_GENERATE, topic_id=topic_id)
    resp = llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[])
    problem = parse_problem_json(resp.text)
    index_question(
        session,
        text=problem,
        source_ref=f"productive_failure:{concept.id}:{content_hash(problem)}",
        topic_id=topic_id,
        concept_id=concept.id,
    )
    session.commit()
    return problem


def consolidate(
    session: Session, concept: Concept, problem: str, attempt: str, *, llm: LLMClient
) -> ConsolidateResult:
    """Grade the generative attempt and teach the canonical approach; persist the record."""
    user = (f"CONCEPT: {concept.name}\n\n<<<PROBLEM>>>\n{problem}\n<<<END_PROBLEM>>>\n\n"
            f"<<<ATTEMPT>>>\n{attempt or '(none)'}\n<<<END_ATTEMPT>>>")
    topic_id = topic_id_for_concept(session, concept.id)
    trace_prompt(session, PF_CONSOLIDATE, topic_id=topic_id)
    resp = llm.complete(
        system=PF_CONSOLIDATE, messages=[{"role": "user", "content": user}], tools=[]
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
    session.flush()
    index_assessment(session, assessment, topic_id=topic_id)
    session.commit()
    session.refresh(assessment)
    return ConsolidateResult(
        assessment=assessment, canonical=canonical, feedback=feedback, score=score
    )
