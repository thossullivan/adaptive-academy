import json
from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    Deliverable,
    Item,
    KnowledgeEstimate,
    Rubric,
    SourceDoc,
    TopicFoundation,
    Track,
)

_OMISSION_PENALTY = 0.15


def level_from_score(score: float) -> tuple[str, float]:
    """Map an anchored score (0..1) to a KnowledgeEstimate level + confidence.

    Thresholds are empirical (tune here): >=0.75 high, >=0.45 medium, else low.
    """
    s = max(0.0, min(1.0, score))
    level = "high" if s >= 0.75 else "medium" if s >= 0.45 else "low"
    return level, round(s, 2)


def compute_delta(score: float, baseline_score: float | None) -> float | None:
    if baseline_score is None:
        return None
    return round(score - baseline_score, 4)


def apply_rules_checks(response: str, must_include: list[str], weak_signs: list[str]) -> list[str]:
    """Deterministic anchor checks (§2.3): the LLM grader cannot paper over these."""
    text = response.lower()
    gaps: list[str] = []
    for term in must_include:
        if term and term.lower() not in text:
            gaps.append(f"omitted required element: {term}")
    for sign in weak_signs:
        if sign and sign.lower() in text:
            gaps.append(f"contains likely misconception: {sign}")
    return gaps


def penalize_score(llm_score: float, rules_gaps: list[str]) -> float:
    """Penalize the LLM score for each omitted required element (anti-sycophancy)."""
    omissions = sum(1 for g in rules_gaps if g.startswith("omitted required element"))
    return round(max(0.0, min(1.0, llm_score) - _OMISSION_PENALTY * omissions), 4)


@dataclass
class RubricDraft:
    criteria: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    strong_signs: list[str] = field(default_factory=list)
    weak_signs: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)


@dataclass
class GradeDraft:
    score: float = 0.0
    verdict: str = ""
    gaps: list[str] = field(default_factory=list)
    confidence_actual: float | None = None


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def _as_float(v, default: float | None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_rubric_json(text: str) -> RubricDraft:
    d = json.loads(_strip_fences(text))
    return RubricDraft(
        criteria=list(d.get("criteria", []) or []),
        must_include=list(d.get("must_include", []) or []),
        strong_signs=list(d.get("strong_signs", []) or []),
        weak_signs=list(d.get("weak_signs", []) or []),
        source_refs=list(d.get("source_refs", []) or []),
    )


def parse_grade_json(text: str) -> GradeDraft:
    d = json.loads(_strip_fences(text))
    return GradeDraft(
        score=_as_float(d.get("score"), 0.0) or 0.0,
        verdict=str(d.get("verdict", "")),
        gaps=list(d.get("gaps", []) or []),
        confidence_actual=_as_float(d.get("confidence_actual"), None),
    )


_RUBRIC_SYSTEM = (
    "You build a grading rubric for one concept an advanced learner must explain. "
    "Given the concept, the topic foundation, and sources, produce a rubric to grade a "
    "learner's *explanation* against — NOT a model answer. Respond with ONLY a JSON object: "
    '{"criteria": [str, prose points a correct explanation must address], '
    '"must_include": [str, short LITERAL terms/expressions a correct explanation must '
    'contain, e.g. "softmax", "QK^T", "scale by sqrt(d)"], "strong_signs": [str], '
    '"weak_signs": [str, common misconceptions/red flags], "source_refs": [str]}. '
    "Keep must_include to 3-6 precise, checkable terms. No prose outside the JSON."
)


def _topic_id_for(session: Session, concept: Concept) -> int:
    return session.get(Track, concept.track_id).topic_id


def build_rubric_prompt(concept_name: str, foundation: TopicFoundation | None,
                        sources: list[SourceDoc]) -> tuple[str, str]:
    lines = [f"CONCEPT: {concept_name}"]
    if foundation:
        lines.append(f"FOUNDATION OVERVIEW: {foundation.overview}")
        lines.append(f"KEY CONCEPTS: {', '.join(foundation.key_concepts)}")
    if sources:
        lines.append("SOURCES:")
        for s in sources:
            lines.append(f"- [{s.tier}] {s.title} — {s.summary}".rstrip(" —"))
    return _RUBRIC_SYSTEM, "\n".join(lines)


def ensure_rubric(session: Session, concept: Concept, *, llm: LLMClient) -> Rubric:
    """Get the concept's rubric, generating + caching it on first use (§2.1)."""
    existing = session.exec(select(Rubric).where(Rubric.concept_id == concept.id)).first()
    if existing is not None:
        return existing
    topic_id = _topic_id_for(session, concept)
    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)).first()
    sources = session.exec(
        select(SourceDoc).where(SourceDoc.topic_id == topic_id,
                                SourceDoc.status == "accepted")).all()
    system, user = build_rubric_prompt(concept.name, foundation, sources)
    resp = llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[])
    draft = parse_rubric_json(resp.text)
    rubric = Rubric(concept_id=concept.id, criteria=draft.criteria,
                    must_include=draft.must_include, strong_signs=draft.strong_signs,
                    weak_signs=draft.weak_signs, source_refs=draft.source_refs)
    session.add(rubric)
    session.commit()
    session.refresh(rubric)
    return rubric


_GRADE_SYSTEM = (
    "You are a SKEPTICAL grader for an advanced learner's explanation. Grade the "
    "RESPONSE strictly AGAINST the provided rubric/anchor — never from fluency, length, "
    "or confidence. Reward only demonstrated understanding of the listed criteria; "
    "penalize vagueness and missing required elements. Respond with ONLY a JSON object: "
    '{"score": number 0..1, "verdict": str (one sentence), "gaps": [str, specific '
    'missing/incorrect points], "confidence_actual": number 0..1 (same as score)}. '
    "No prose outside the JSON."
)

_PROBE_TEXT = {
    "self_explanation": "Explain *why* {concept} works, in your own words.",
    "calibration": "Explain *why* {concept} works (we will compare to your confidence).",
    "artifact_review": "Review your shipped artifact for {concept}: what does it "
                       "demonstrate you understand, and where are the gaps?",
    "source_quiz": "{question}",
}


@dataclass
class AssessmentResult:
    assessment: Assessment
    estimate: KnowledgeEstimate
    events: list[AgentEvent]


def build_grade_prompt(concept_name: str, kind: str, criteria: list[str],
                       reference: str, response: str) -> tuple[str, str]:
    lines = [f"CONCEPT: {concept_name}", f"PROBE KIND: {kind}", "", "RUBRIC / ANCHOR:"]
    for c in criteria:
        lines.append(f"- {c}")
    if reference:
        lines.append(f"REFERENCE ANSWER: {reference}")
    lines += ["", "LEARNER RESPONSE:", response or "(empty)"]
    return _GRADE_SYSTEM, "\n".join(lines)


def _deliverable_criteria(session: Session, item_id: int | None) -> list[str]:
    if item_id is None:
        return []
    item = session.get(Item, item_id)
    if item is None:
        return []
    d = session.exec(select(Deliverable).where(Deliverable.phase_id == item.phase_id)).first()
    return d.acceptance_criteria if d else []


def assess_concept(
    session: Session,
    concept: Concept,
    kind: str,
    response: str,
    *,
    llm: LLMClient,
    confidence_predicted: float | None = None,
    baseline_id: int | None = None,
    item_id: int | None = None,
) -> AssessmentResult:
    """Run an anchored probe, persist an Assessment, and update the KnowledgeEstimate."""
    events: list[AgentEvent] = []
    topic_id = _topic_id_for(session, concept)

    def emit(k: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic_id, kind=k, detail=detail)
        session.add(ev)
        events.append(ev)

    # Resolve the anchor (rubric vs. acceptance criteria) and the probe text.
    rubric_id: int | None = None
    must_include: list[str] = []
    weak_signs: list[str] = []
    reference = ""
    if kind == "artifact_review":
        criteria = _deliverable_criteria(session, item_id)
        probe = _PROBE_TEXT[kind].format(concept=concept.name)
    else:
        rubric = ensure_rubric(session, concept, llm=llm)
        rubric_id = rubric.id
        criteria, must_include, weak_signs = rubric.criteria, rubric.must_include, rubric.weak_signs
        probe = _PROBE_TEXT.get(kind, _PROBE_TEXT["self_explanation"]).format(
            concept=concept.name, question=concept.name)
    emit("assess:probe", kind)

    system, user = build_grade_prompt(concept.name, kind, criteria, reference, response)
    grade = parse_grade_json(
        llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[]).text)

    rules_gaps = apply_rules_checks(response, must_include, weak_signs)
    if rules_gaps:
        emit("assess:rules", f"{len(rules_gaps)} hard gap(s)")
    final_score = penalize_score(grade.score, rules_gaps)
    gaps = list(grade.gaps) + rules_gaps
    emit("assess:graded", f"score={final_score}")

    baseline = session.get(Assessment, baseline_id) if baseline_id else None
    delta = compute_delta(final_score, baseline.score if baseline else None)
    confidence_actual = final_score if kind == "calibration" else grade.confidence_actual

    assessment = Assessment(
        concept_id=concept.id, item_id=item_id, kind=kind, prompt=probe, response=response,
        verdict=grade.verdict, score=final_score, gaps=gaps,
        confidence_predicted=confidence_predicted, confidence_actual=confidence_actual,
        rubric_id=rubric_id, baseline_assessment_id=baseline_id, delta=delta)
    session.add(assessment)

    level, conf = level_from_score(final_score)
    estimate = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept.id)).first()
    if estimate is None:
        estimate = KnowledgeEstimate(concept_id=concept.id)
        session.add(estimate)
    estimate.level, estimate.confidence = level, conf
    emit("assess:estimate", f"level={level}")

    emit("assess:done", f"concept {concept.id}")
    session.commit()
    session.refresh(assessment)
    session.refresh(estimate)
    return AssessmentResult(assessment=assessment, estimate=estimate, events=events)
