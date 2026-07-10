"""Milestone gate verdicts — pure functions over existing evidence rows (spec §4.2).

A gate 'passes' only on evidence: every load-bearing concept under the milestone needs
(a) a DELAYED unassisted recall that held (the Decay-Check machinery, required not
suggested) and (b) an artifact-grade assessment at/above threshold. No LLM calls —
deterministic, testable, and impossible to sweet-talk (the anti-illusion-of-competence
design, parallel to Plan 1's attempt-gate and Plan 4's rules layer).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from adaptive_academy.models import AgentEvent, Assessment, Concept, Milestone, ProgramTopicLink, Track

DELAY_DAYS = 7          # recall must be >= this many days after the prior engagement
HELD_RATIO = 0.85       # mirrors engine/decay.py: recall keeps >=85% of prior score
ARTIFACT_THRESHOLD = 0.7
ARTIFACT_KINDS = {"artifact_review", "teach", "productive_failure"}


def _naive_utc(dt: datetime) -> datetime:
    """SQLite round-trips datetimes tz-stripped; compare everything tz-naive."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


@dataclass
class ConceptEvidence:
    concept_id: int
    name: str
    delayed_ok: bool
    artifact_ok: bool
    verdict: str  # verified | stale | weak_artifact | never_probed_cold


@dataclass
class GateReport:
    milestone_id: int
    verdict: str  # passed | open | overridden
    reason: str
    concepts: list[ConceptEvidence]


def evaluate_concept(concept_id: int, name: str, assessments: list[Assessment]) -> ConceptEvidence:
    """Pure verdict for one concept from its assessment history.

    The MOST RECENT delayed recall decides held-vs-decayed: an old success must not
    mask later forgetting. A recall is 'delayed' iff it comes >= DELAY_DAYS after the
    closest prior non-recall assessment (fresh-engagement baseline).
    """
    rows = sorted(assessments, key=lambda a: a.id or 0)
    last_delayed_held: bool | None = None  # None = no delayed recall seen
    for i, r in enumerate(rows):
        if r.kind != "recall":
            continue
        prior = next((p for p in reversed(rows[:i]) if p.kind != "recall"), None)
        if prior is None:
            continue
        gap = _naive_utc(r.created_at) - _naive_utc(prior.created_at)
        if gap < timedelta(days=DELAY_DAYS):
            continue
        last_delayed_held = r.score >= prior.score * HELD_RATIO

    artifact_ok = any(
        a.kind in ARTIFACT_KINDS and a.score >= ARTIFACT_THRESHOLD for a in rows
    )
    delayed_ok = last_delayed_held is True

    if last_delayed_held is None:
        verdict = "never_probed_cold"
    elif last_delayed_held is False:
        verdict = "stale"
    elif not artifact_ok:
        verdict = "weak_artifact"
    else:
        verdict = "verified"
    return ConceptEvidence(concept_id=concept_id, name=name,
                           delayed_ok=delayed_ok, artifact_ok=artifact_ok, verdict=verdict)


def milestone_load_bearing(session: Session, milestone: Milestone) -> list[Concept]:
    links = session.exec(
        select(ProgramTopicLink).where(
            ProgramTopicLink.milestone_id == milestone.id,
            ProgramTopicLink.status == "started",
        )
    ).all()
    topic_ids = [link.topic_id for link in links if link.topic_id is not None]
    if not topic_ids:
        return []
    return session.exec(
        select(Concept)
        .join(Track)
        .where(Track.topic_id.in_(topic_ids), Concept.is_load_bearing == True)  # noqa: E712
    ).all()


def milestone_gate(session: Session, milestone: Milestone) -> GateReport:
    """Compute the gate report and sync `milestone.gate_status`.

    Evidence-passed always wins (supersedes an override, spec §4.3). A stored 'passed'
    that no longer holds is honestly downgraded to 'open'. 'overridden' is sticky
    unless evidence passes.
    """
    concepts = milestone_load_bearing(session, milestone)
    evidences: list[ConceptEvidence] = []
    for c in concepts:
        rows = session.exec(
            select(Assessment).where(Assessment.concept_id == c.id)
        ).all()
        evidences.append(evaluate_concept(c.id, c.name, rows))

    if not evidences:
        passed, reason = False, "no evidence yet: no started topics with load-bearing concepts"
    else:
        unverified = [e for e in evidences if e.verdict != "verified"]
        passed = not unverified
        reason = (
            "all load-bearing concepts verified (delayed recall held + artifact graded)"
            if passed
            else f"{len(unverified)} of {len(evidences)} load-bearing concepts unverified"
        )

    if passed:
        new_status = "passed"
    elif milestone.gate_status == "overridden":
        new_status = "overridden"
    else:
        new_status = "open"
    if new_status != milestone.gate_status:
        if new_status == "passed":
            # Timestamped signal for the revision nudge (spec §4.4): emitted only
            # on the transition, never on a re-evaluation that stays passed.
            session.add(AgentEvent(program_id=milestone.program_id,
                                   kind="program:gate_passed",
                                   detail=f"milestone {milestone.id}"))
        milestone.gate_status = new_status
        session.add(milestone)
        session.commit()
        session.refresh(milestone)

    return GateReport(milestone_id=milestone.id, verdict=milestone.gate_status,
                      reason=reason, concepts=evidences)
