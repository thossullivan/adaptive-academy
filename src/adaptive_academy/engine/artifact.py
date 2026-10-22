"""Project / artifact assessment — grade the shipped work against its acceptance criteria.

Authentic, artifact-first assessment is the highest-value method for advanced learners. The
learner ships a phase deliverable (a URL + the artifact content); we grade the CONTENT against
the deliverable's `acceptance_criteria` with the same skeptical, mechanism-anchored philosophy
as `assess.grade`, write the verdict onto the deliverable, and record an `artifact_review`
assessment for each concept the phase was meant to demonstrate (its items' `concept_refs`).
That powers the hard-to-game "shipped" competence signal.

v1 ingests PASTED content (the learner's writeup / key code / ablation). The artifact_url is
stored for reference; server-side URL fetching (SSRF surface) and sandboxed execution are
deferred — both become additional signals feeding the same deliverable verdict, not a rewrite.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.engine.assess import _NO_MECHANISM_CEIL, parse_grade_json
from adaptive_academy.engine.fetch import fetch_artifact_text
from adaptive_academy.engine.trace import trace_prompt
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import AgentEvent, Assessment, Concept, Deliverable, Item, Phase, Track
from adaptive_academy.prompts import ASSESS_ARTIFACT
from adaptive_academy.engine.untrusted import escape_markers


@dataclass
class ArtifactReviewResult:
    score: float
    verdict: str
    gaps: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)  # demonstrated concept names


def _merge_artifact_text(fetched: str | None, content: str) -> str:
    """Combine best-effort-fetched URL text with the learner's pasted notes for grading.
    Both land inside the prompt's <<<ARTIFACT>>> block (so both get injection-immunity)."""
    blocks: list[str] = []
    if fetched:
        blocks.append(f"[Fetched from artifact URL]\n{fetched}")
    if content:
        blocks.append(f"[Submitted notes]\n{content}" if fetched else content)
    return "\n\n".join(blocks)


def phase_concepts(session: Session, phase: Phase) -> list[Concept]:
    """Concepts a phase demonstrates: its items' concept_refs (names) matched to Concept rows."""
    names: set[str] = set()
    for it in session.exec(select(Item).where(Item.phase_id == phase.id)).all():
        for n in it.concept_refs or []:
            names.add(str(n).strip().lower())
    if not names:
        return []
    track_concepts = session.exec(select(Concept).where(Concept.track_id == phase.track_id)).all()
    return [c for c in track_concepts if c.name.strip().lower() in names]


def build_artifact_prompt(deliverable: Deliverable, content: str) -> tuple[str, str]:
    lines = [f"DELIVERABLE: {deliverable.text}", "ACCEPTANCE CRITERIA:"]
    for c in deliverable.acceptance_criteria or []:
        lines.append(f"- {c}")
    lines += ["", "<<<ARTIFACT>>>", escape_markers(content or "(empty)"), "<<<END_ARTIFACT>>>"]
    return ASSESS_ARTIFACT, "\n".join(lines)


def review_artifact(
    session: Session,
    deliverable: Deliverable,
    artifact_url: str,
    content: str,
    *,
    llm: LLMClient,
    fetch: Callable[[str], str | None] = fetch_artifact_text,
) -> ArtifactReviewResult:
    """Grade the shipped artifact against the deliverable's criteria; persist the verdict +
    a per-concept artifact_review (the 'shipped' signal). The mechanism cap applies.

    If an artifact_url is given, its text is best-effort fetched (SSRF-guarded) and graded
    alongside the pasted content; a fetch failure degrades silently to paste-only."""
    if artifact_url:
        deliverable.artifact_url = artifact_url

    fetched = fetch(artifact_url) if artifact_url else None
    graded_content = _merge_artifact_text(fetched, content)

    phase = session.get(Phase, deliverable.phase_id)
    topic_id = session.get(Track, phase.track_id).topic_id if phase else None

    system, user = build_artifact_prompt(deliverable, graded_content)
    trace_prompt(session, ASSESS_ARTIFACT, topic_id=topic_id)
    grade = parse_grade_json(
        llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[]).text)

    score = grade.score
    if not grade.mechanism_present:
        score = min(score, _NO_MECHANISM_CEIL)  # the artifact doesn't actually demonstrate it
    score = round(max(0.0, min(1.0, score)), 4)

    deliverable.review_verdict = grade.verdict
    session.add(deliverable)

    concepts = phase_concepts(session, phase) if phase else []
    # The shipped signal only: artifact_review is outside assess.GRADING_KINDS, so these rows
    # never write the KnowledgeEstimate and never make a concept's prior read as a grade.
    for c in concepts:
        session.add(Assessment(
            concept_id=c.id, kind="artifact_review",
            prompt=f"Ship: {deliverable.text[:80]}", response=content[:2000],
            verdict=grade.verdict, score=score, gaps=grade.gaps,
            prompt_tag=ASSESS_ARTIFACT.tag))
    session.add(AgentEvent(
        topic_id=topic_id, kind="artifact:reviewed",
        detail=f"score={score}, {len(concepts)} concept(s)"))
    session.commit()
    session.refresh(deliverable)
    return ArtifactReviewResult(
        score=score, verdict=grade.verdict, gaps=grade.gaps, concepts=[c.name for c in concepts])
