from adaptive_academy.engine.runlock import RunInProgress
from adaptive_academy.llm.types import StructuredOutputError
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.api.schemas import (
    AcceptIn,
    ConceptEvidenceOut,
    CreateProgramIn,
    EventOut,
    GateReportOut,
    LinkOut,
    MapChangeOut,
    MapRevisionOut,
    MilestoneOut,
    MilestoneUpdateIn,
    OverrideIn,
    ProgramDetailOut,
    ProgramOut,
    StartOut,
)
from adaptive_academy.engine.gates import milestone_gate
from adaptive_academy.engine.program_research import research_program
from adaptive_academy.engine.revision import (
    apply_change,
    reject_change,
    revision_suggested,
    run_revision,
)
from adaptive_academy.llm.researcher_types import ResearcherClient
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    MapChange,
    MapRevision,
    Milestone,
    Program,
    ProgramIntent,
    ProgramTopicLink,
    Topic,
    TopicIntent,
    now_utc,
)

router = APIRouter(prefix="/api/programs", tags=["programs"])


def _program_or_404(session: Session, program_id: int) -> Program:
    program = session.get(Program, program_id)
    if program is None:
        raise HTTPException(404, "program not found")
    return program


def _milestone_or_404(session: Session, program_id: int, milestone_id: int) -> Milestone:
    m = session.get(Milestone, milestone_id)
    if m is None or m.program_id != program_id:
        raise HTTPException(404, "milestone not found")
    return m


def _link_out(link: ProgramTopicLink) -> LinkOut:
    return LinkOut(id=link.id, status=link.status, proposed_title=link.proposed_title,
                   why=link.why, sources=link.sources, topic_id=link.topic_id,
                   added_by=link.added_by)


def _milestone_out(session: Session, m: Milestone) -> MilestoneOut:
    links = session.exec(
        select(ProgramTopicLink).where(ProgramTopicLink.milestone_id == m.id)
    ).all()
    return MilestoneOut(id=m.id, title=m.title, success_criteria=m.success_criteria,
                        order_index=m.order_index, gate_status=m.gate_status,
                        depends_on=m.depends_on, override_reason=m.override_reason,
                        links=[_link_out(link) for link in links], archived=m.archived)


def _program_out(session: Session, p: Program) -> ProgramOut:
    count = len(session.exec(select(Milestone).where(Milestone.program_id == p.id)).all())
    return ProgramOut(id=p.id, title=p.title, goal_statement=p.goal_statement,
                      status=p.status, milestone_count=count)


def _open_revision(session: Session, program_id: int) -> MapRevision | None:
    change = session.exec(
        select(MapChange).join(MapRevision).where(
            MapRevision.program_id == program_id, MapChange.status == "proposed")
    ).first()
    return session.get(MapRevision, change.revision_id) if change else None


def _detail(session: Session, p: Program) -> ProgramDetailOut:
    milestones = session.exec(
        select(Milestone).where(Milestone.program_id == p.id).order_by(Milestone.order_index)
    ).all()
    return ProgramDetailOut(
        program=_program_out(session, p),
        milestones=[_milestone_out(session, m) for m in milestones],
        revision_suggested=revision_suggested(session, p),
        has_open_revision=_open_revision(session, p.id) is not None,
    )


@router.post("", response_model=ProgramOut)
def create_program(body: CreateProgramIn, session: Session = Depends(get_session)):
    program = Program(title=body.title, goal_statement=body.goal_statement)
    session.add(program)
    session.commit()
    session.refresh(program)
    session.add(ProgramIntent(
        program_id=program.id, target_depth=body.target_depth,
        prior_knowledge=body.prior_knowledge, weekly_time_budget=body.weekly_time_budget,
        horizon=body.horizon, focus_area=body.focus_area))
    session.commit()
    return _program_out(session, program)


@router.get("", response_model=list[ProgramOut])
def list_programs(session: Session = Depends(get_session)):
    return [_program_out(session, p) for p in session.exec(select(Program)).all()]


@router.get("/{program_id}", response_model=ProgramDetailOut)
def get_program(program_id: int, session: Session = Depends(get_session)):
    return _detail(session, _program_or_404(session, program_id))


@router.post("/{program_id}/research", response_model=ProgramDetailOut)
def run_program_research(
    program_id: int,
    session: Session = Depends(get_session),
    researcher: ResearcherClient = Depends(get_researcher),
    llm: LLMClient = Depends(get_llm),
):
    program = _program_or_404(session, program_id)
    intent = session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == program_id)
    ).first()
    if intent is None:
        raise HTTPException(400, "program has no intent")
    try:
        research_program(session, program, intent, researcher=researcher, llm=llm)
    except StructuredOutputError:
        raise  # a model failure, not bad input: the app-level 502 handler
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _detail(session, program)


@router.put("/{program_id}/milestones/{milestone_id}", response_model=MilestoneOut)
def update_milestone(
    program_id: int, milestone_id: int, body: MilestoneUpdateIn,
    session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    m = _milestone_or_404(session, program_id, milestone_id)
    if body.title is not None:
        m.title = body.title
    if body.success_criteria is not None:
        m.success_criteria = body.success_criteria
    if body.order_index is not None:
        m.order_index = body.order_index
    if body.depends_on is not None:
        m.depends_on = body.depends_on
    program.updated_at = now_utc()
    session.add(m)
    session.add(program)
    session.commit()
    session.refresh(m)
    return _milestone_out(session, m)


@router.post("/{program_id}/accept", response_model=ProgramDetailOut)
def accept_program(
    program_id: int, body: AcceptIn, session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    milestone_ids = [m.id for m in session.exec(
        select(Milestone).where(Milestone.program_id == program_id)).all()]
    links = session.exec(
        select(ProgramTopicLink).where(ProgramTopicLink.milestone_id.in_(milestone_ids))
    ).all() if milestone_ids else []
    by_id = {link.id: link for link in links}
    for lid in body.accepted_link_ids:
        if lid in by_id and by_id[lid].status == "proposed":
            by_id[lid].status = "stub"
    for lid in body.pruned_link_ids:
        if lid in by_id and by_id[lid].status == "proposed":
            by_id[lid].status = "pruned"
    program.updated_at = now_utc()
    session.add(program)
    session.commit()
    return _detail(session, program)


@router.post("/{program_id}/links/{link_id}/start", response_model=StartOut)
def start_link(
    program_id: int, link_id: int, session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    link = session.get(ProgramTopicLink, link_id)
    if link is None:
        raise HTTPException(404, "link not found")
    milestone = session.get(Milestone, link.milestone_id)
    if milestone is None or milestone.program_id != program_id:
        raise HTTPException(404, "link not found")
    if link.status == "started" and link.topic_id is not None:
        return StartOut(topic_id=link.topic_id)  # idempotent
    if milestone.archived:
        raise HTTPException(400, "milestone archived")
    if link.status != "stub":
        raise HTTPException(400, f"link is {link.status}, not stub")

    intent = session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == program_id)
    ).first()
    topic = Topic(title=link.proposed_title)
    session.add(topic)
    session.commit()
    session.refresh(topic)
    goal = (f"{link.proposed_title} — part of program '{program.title}' "
            f"({program.goal_statement}). Milestone: {milestone.title} — "
            f"{milestone.success_criteria}")
    session.add(TopicIntent(
        topic_id=topic.id, goal=goal,
        prior_knowledge=intent.prior_knowledge if intent else "",
        time_budget=intent.weekly_time_budget if intent else ""))
    link.topic_id = topic.id
    link.status = "started"
    program.updated_at = now_utc()
    session.add(link)
    session.add(program)
    session.add(AgentEvent(program_id=program_id, kind="program:topic_started",
                           detail=f"link {link.id} → topic {topic.id}"))
    session.commit()
    return StartOut(topic_id=topic.id)


@router.get("/{program_id}/milestones/{milestone_id}/gate", response_model=GateReportOut)
def get_gate(
    program_id: int, milestone_id: int, session: Session = Depends(get_session),
):
    _program_or_404(session, program_id)
    m = _milestone_or_404(session, program_id, milestone_id)
    if m.archived:
        raise HTTPException(400, "milestone archived")
    report = milestone_gate(session, m)
    return GateReportOut(
        milestone_id=report.milestone_id, verdict=report.verdict, reason=report.reason,
        concepts=[ConceptEvidenceOut(concept_id=e.concept_id, name=e.name,
                                     delayed_ok=e.delayed_ok, artifact_ok=e.artifact_ok,
                                     verdict=e.verdict) for e in report.concepts])


@router.post("/{program_id}/milestones/{milestone_id}/override", response_model=MilestoneOut)
def override_gate(
    program_id: int, milestone_id: int, body: OverrideIn,
    session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    m = _milestone_or_404(session, program_id, milestone_id)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, "override requires a reason")
    m.gate_status = "overridden"
    m.override_reason = reason
    program.updated_at = now_utc()
    session.add(m)
    session.add(program)
    session.add(AgentEvent(program_id=program_id, kind="program:gate_override",
                           detail=f"milestone {m.id}: {reason}"))
    session.commit()
    session.refresh(m)
    return _milestone_out(session, m)


@router.get("/{program_id}/events", response_model=list[EventOut])
def list_program_events(program_id: int, session: Session = Depends(get_session)):
    _program_or_404(session, program_id)
    rows = session.exec(
        select(AgentEvent).where(AgentEvent.program_id == program_id)
        .order_by(AgentEvent.id)
    ).all()
    return [EventOut(kind=e.kind, detail=e.detail, created_at=e.created_at) for e in rows]


def _revision_out(session: Session, rev: MapRevision) -> MapRevisionOut:
    changes = session.exec(
        select(MapChange).where(MapChange.revision_id == rev.id).order_by(MapChange.id)
    ).all()
    return MapRevisionOut(
        id=rev.id, map_health=rev.map_health,
        changes=[MapChangeOut(id=c.id, kind=c.kind, payload=c.payload, why=c.why,
                              source_urls=c.source_urls, status=c.status)
                 for c in changes])


@router.post("/{program_id}/revise", response_model=MapRevisionOut)
def revise_map(
    program_id: int,
    session: Session = Depends(get_session),
    researcher: ResearcherClient = Depends(get_researcher),
    llm: LLMClient = Depends(get_llm),
):
    program = _program_or_404(session, program_id)
    intent = session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == program_id)
    ).first()
    try:
        result = run_revision(session, program, intent, researcher=researcher, llm=llm)
    except RunInProgress as e:
        raise HTTPException(409, str(e)) from e
    except StructuredOutputError:
        raise  # a model failure, not bad input: the app-level 502 handler
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _revision_out(session, result.revision)


@router.get("/{program_id}/revision", response_model=MapRevisionOut)
def get_open_revision(program_id: int, session: Session = Depends(get_session)):
    _program_or_404(session, program_id)
    rev = _open_revision(session, program_id)
    if rev is None:
        raise HTTPException(404, "no open revision")
    return _revision_out(session, rev)


def _change_or_404(session: Session, program_id: int, change_id: int) -> MapChange:
    change = session.get(MapChange, change_id)
    if change is None:
        raise HTTPException(404, "change not found")
    rev = session.get(MapRevision, change.revision_id)
    if rev is None or rev.program_id != program_id:
        raise HTTPException(404, "change not found")
    return change


@router.post("/{program_id}/changes/{change_id}/accept", response_model=ProgramDetailOut)
def accept_change(
    program_id: int, change_id: int, session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    change = _change_or_404(session, program_id, change_id)
    try:
        apply_change(session, program, change)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    session.add(AgentEvent(program_id=program_id, kind="program:change_accepted",
                           detail=f"{change.kind} (change {change.id})"))
    session.commit()
    return _detail(session, program)


@router.post("/{program_id}/changes/{change_id}/reject", response_model=ProgramDetailOut)
def reject_change_route(
    program_id: int, change_id: int, session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    change = _change_or_404(session, program_id, change_id)
    try:
        reject_change(session, change)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _detail(session, program)
