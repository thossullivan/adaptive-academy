"""Program-level research fan-out (spec §4.1) — Plan 2's muscle at program scale.

Fans out program-shaped angles (PhD curricula, canonical courses, roadmaps, reading
lists, prerequisite structures), then one structured synthesis call drafts milestones
+ candidate topics for human review. Nothing is materialized here beyond the proposal
rows (Milestone + ProgramTopicLink status=proposed).
"""

from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.engine.fanout import fan_out_with_retry
from adaptive_academy.jsonout import dropped_summary, require_list, require_object, str_items
from adaptive_academy.llm.researcher_types import RawSource, ResearcherClient, SearchBrief
from adaptive_academy.llm.structured import structured_json
from adaptive_academy.llm.types import LLMClient, StructuredOutputError
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


def parse_program_obj(data: object, *, dropped: list[str] | None = None) -> list[MilestoneDraft]:
    """Parse the synthesis payload; depends_on keeps only valid BACKWARD indices.

    Defence behind the schema check (llm/schema_check.py): a milestone or topic that isn't
    an object is skipped and its JSON path appended to `dropped`, and depends_on indices are
    renumbered past a skipped milestone (a dependency on it is dropped). An answer with
    nothing usable (not an object, `milestones` not a list, or milestones of which none is
    an object) is a StructuredOutputError.
    """
    dropped = [] if dropped is None else dropped
    data = require_object(data, "program synthesis")
    raw = require_list(data, "milestones", "program synthesis")
    drafts: list[MilestoneDraft] = []
    kept: dict[int, int] = {}  # the model's milestone index -> its draft's index
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            dropped.append(f"$.milestones[{i}]")
            continue
        raw_deps = m.get("depends_on") if isinstance(m.get("depends_on"), list) else []
        deps = [kept[int(j)] for j in raw_deps
                if isinstance(j, (int, float)) and not isinstance(j, bool)
                and 0 <= int(j) < i and int(j) in kept]
        raw_topics = m.get("topics") or []
        if not isinstance(raw_topics, list):
            dropped.append(f"$.milestones[{i}].topics")
            raw_topics = []
        topics: list[TopicDraft] = []
        for k, t in enumerate(raw_topics):
            if not isinstance(t, dict):
                dropped.append(f"$.milestones[{i}].topics[{k}]")
            elif t.get("title"):
                topics.append(TopicDraft(title=str(t.get("title", "")), why=str(t.get("why", "")),
                                         source_urls=str_items(t.get("source_urls"))))
        kept[i] = len(drafts)
        drafts.append(MilestoneDraft(title=str(m.get("title", "")),
                                     success_criteria=str(m.get("success_criteria", "")),
                                     depends_on=sorted(set(deps)), topics=topics))
    if raw and not drafts:
        raise StructuredOutputError(
            "malformed", f"program synthesis: none of its {len(raw)} milestones is an object")
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

    per_brief, failures, recovered = fan_out_with_retry(briefs, researcher, max_workers)

    raw: list[RawSource] = []
    for i, brief in enumerate(briefs):
        for s in per_brief[i]:
            s.angle = brief.angle
        if i in failures:
            emit("program_research:subagent_error", f"{brief.angle}: {failures[i]}")
        elif i in recovered:
            emit("program_research:subagent_retry",
                 f"{brief.angle}: recovered {recovered[i]} sources")
        else:
            emit("program_research:subagent", f"{brief.angle}: {len(per_brief[i])} sources")
        raw.extend(per_brief[i])

    if briefs and not raw:
        # Zero sources — whether every angle errored or they all "succeeded" with empty
        # results (the historical silent-failure signature: fan-outs returning [] from
        # truncated JSON caused real ungrounded runs), there is nothing to ground a
        # synthesis in. Persist the trace (subagent events) so the failure is
        # observable, but do not run synthesis or persist any proposal: the LLM would
        # otherwise fabricate milestones from zero sources, and a persisted proposal
        # blocks re-research.
        session.commit()
        raise ValueError(
            "research produced no sources; retry when connectivity is restored"
        )

    emit("prompt", PROGRAM_SYNTHESIS.tag)
    data = structured_json(
        llm, PROGRAM_SYNTHESIS,
        [{"role": "user", "content": _build_synthesis_user_msg(program, intent, raw)}],
        schema=PROGRAM_SCHEMA, tool_name="emit_program",
    )
    malformed: list[str] = []
    drafts = parse_program_obj(data, dropped=malformed)
    if malformed:
        emit("program_research:malformed", dropped_summary(malformed))
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
