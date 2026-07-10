"""Program-level research fan-out (spec §4.1) — Plan 2's muscle at program scale.

Fans out program-shaped angles (PhD curricula, canonical courses, roadmaps, reading
lists, prerequisite structures), then one structured synthesis call drafts milestones
+ candidate topics for human review. Nothing is materialized here beyond the proposal
rows (Milestone + ProgramTopicLink status=proposed).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.llm.researcher_types import RawSource, ResearcherClient, SearchBrief
from adaptive_academy.llm.structured import structured_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.prompts import PROGRAM_SYNTHESIS
from adaptive_academy.models import AgentEvent, Milestone, Program, ProgramIntent, ProgramTopicLink

# (angle_key, query_template) — {goal}/{focus} are filled in. Order is the fan-out order.
PROGRAM_ANGLES: list[tuple[str, str]] = [
    ("phd_curricula", "PhD qualifying exam syllabi and graduate curricula for {goal} (focus: {focus})"),
    ("canonical_courses", "Canonical graduate courses and lecture series covering {goal} (focus: {focus})"),
    ("practitioner_roadmaps", "Practitioner roadmaps and self-study guides to expert level in {goal} (focus: {focus})"),
    ("reading_lists", "Primary-literature reading lists and seminal papers for {focus} within {goal}"),
    ("prerequisite_structures", "Prerequisite structure and foundational math/CS required for {goal} (focus: {focus})"),
]


def build_program_briefs(goal: str, focus: str, n: int) -> list[SearchBrief]:
    """Deterministic program-shaped fan-out angles. Caps at the defined ANGLES."""
    count = max(0, min(n, len(PROGRAM_ANGLES)))
    return [SearchBrief(angle=a, query=t.format(goal=goal, focus=focus or goal))
            for a, t in PROGRAM_ANGLES[:count]]


PROGRAM_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "milestones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "success_criteria": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "integer"}},
                    "topics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "why": {"type": "string"},
                                "source_urls": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["title", "success_criteria", "topics"],
            },
        },
    },
    "required": ["milestones"],
}


@dataclass
class TopicDraft:
    title: str
    why: str = ""
    source_urls: list[str] = field(default_factory=list)


@dataclass
class MilestoneDraft:
    title: str
    success_criteria: str
    depends_on: list[int]
    topics: list[TopicDraft]


def parse_program_obj(data: dict) -> list[MilestoneDraft]:
    """Parse the synthesis payload; depends_on keeps only valid BACKWARD indices."""
    drafts: list[MilestoneDraft] = []
    for i, m in enumerate(data.get("milestones", []) or []):
        deps = [int(j) for j in (m.get("depends_on", []) or [])
                if isinstance(j, (int, float)) and 0 <= int(j) < i]
        topics = [TopicDraft(title=str(t.get("title", "")), why=str(t.get("why", "")),
                             source_urls=list(t.get("source_urls", []) or []))
                  for t in (m.get("topics", []) or []) if t.get("title")]
        drafts.append(MilestoneDraft(title=str(m.get("title", "")),
                                     success_criteria=str(m.get("success_criteria", "")),
                                     depends_on=sorted(set(deps)), topics=topics))
    return drafts


def _build_synthesis_user_msg(program: Program, intent: ProgramIntent,
                              sources: list[RawSource]) -> str:
    lines = [
        f"PROGRAM GOAL: {program.goal_statement or program.title}",
        f"FOCUS AREA: {intent.focus_area}",
        f"TARGET DEPTH: {intent.target_depth}",
        f"PRIOR KNOWLEDGE: {intent.prior_knowledge}",
        f"WEEKLY TIME BUDGET: {intent.weekly_time_budget}",
        f"HORIZON: {intent.horizon}",
        "",
        "<<<SOURCES>>>",
    ]
    for s in sources:
        lines.append(f"- [{s.angle}] {s.title} ({s.url}) — {s.summary}".rstrip(" —"))
    lines.append("<<<END_SOURCES>>>")
    return "\n".join(lines)


@dataclass
class ProgramResearchResult:
    milestones: list[Milestone]
    links: list[ProgramTopicLink]
    events: list[AgentEvent]


def research_program(
    session: Session,
    program: Program,
    intent: ProgramIntent,
    *,
    researcher: ResearcherClient,
    llm: LLMClient,
    max_subagents: int = 5,
    max_workers: int = 5,
) -> ProgramResearchResult:
    """Fan out, synthesize a milestone proposal, persist proposal rows, trace."""
    existing = session.exec(
        select(Milestone).where(Milestone.program_id == program.id)
    ).first()
    if existing is not None:
        raise ValueError("program already has a proposal")

    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(program_id=program.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    briefs = build_program_briefs(program.goal_statement or program.title,
                                  intent.focus_area, max_subagents)
    emit("program_research:plan", f"{len(briefs)} briefs")

    per_brief: list[list[RawSource]] = [[] for _ in briefs]
    failures: dict[int, str] = {}
    if briefs:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(briefs)))) as ex:
            futures = {ex.submit(researcher.search, b): i for i, b in enumerate(briefs)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    per_brief[idx] = fut.result()
                except Exception as e:  # noqa: BLE001
                    failures[idx] = type(e).__name__

    raw: list[RawSource] = []
    for i, brief in enumerate(briefs):
        for s in per_brief[i]:
            s.angle = brief.angle
        if i in failures:
            emit("program_research:subagent_error", f"{brief.angle}: {failures[i]}")
        else:
            emit("program_research:subagent", f"{brief.angle}: {len(per_brief[i])} sources")
        raw.extend(per_brief[i])

    if briefs and len(failures) == len(briefs):
        # Every angle failed (as opposed to some angles merely returning zero results) —
        # there is nothing to ground a synthesis in. Persist the trace (subagent_error
        # events) so the failure is observable, but do not run synthesis or persist any
        # proposal: the LLM would otherwise fabricate milestones from zero sources, and
        # a persisted proposal blocks re-research.
        session.commit()
        raise ValueError(
            "research found no sources (all angles failed); "
            "retry when connectivity is restored"
        )

    emit("prompt", PROGRAM_SYNTHESIS.tag)
    data = structured_json(
        llm, PROGRAM_SYNTHESIS,
        [{"role": "user", "content": _build_synthesis_user_msg(program, intent, raw)}],
        schema=PROGRAM_SCHEMA, tool_name="emit_program",
    )
    drafts = parse_program_obj(data)
    emit("program_research:synth", f"{len(drafts)} milestones proposed")

    milestones: list[Milestone] = []
    for i, d in enumerate(drafts):
        m = Milestone(program_id=program.id, title=d.title,
                      success_criteria=d.success_criteria, order_index=i)
        session.add(m)
        milestones.append(m)
    session.flush()  # assigns autoincrement ids without committing
    # second pass: map draft indices → milestone ids
    for i, d in enumerate(drafts):
        if d.depends_on:
            milestones[i].depends_on = [milestones[j].id for j in d.depends_on]
            session.add(milestones[i])

    links: list[ProgramTopicLink] = []
    for i, d in enumerate(drafts):
        for t in d.topics:
            link = ProgramTopicLink(milestone_id=milestones[i].id, status="proposed",
                                    proposed_title=t.title, why=t.why,
                                    sources=t.source_urls)
            session.add(link)
            links.append(link)

    emit("program_research:done", f"{len(links)} topic candidates")
    session.commit()
    for m in milestones:
        session.refresh(m)
    for link in links:
        session.refresh(link)
    return ProgramResearchResult(milestones=milestones, links=links, events=events)
