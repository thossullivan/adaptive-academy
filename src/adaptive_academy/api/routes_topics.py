from collections.abc import Callable
from typing import Optional

from adaptive_academy.engine.runlock import RunInProgress, is_running
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

from adaptive_academy.api.deps import (
    get_fetcher,
    get_llm,
    get_researcher,
    get_retriever,
    get_session,
)
from adaptive_academy.api.schemas import (
    ConceptOut,
    CreateTopicIn,
    CurriculumOut,
    DeliverableOut,
    EventOut,
    FoundationOut,
    ImportMarkdownIn,
    IntentOut,
    ItemOut,
    PhaseOut,
    ProgramContextOut,
    ResearchOut,
    ReviewSourcesIn,
    SidebarOut,
    SourceDocOut,
    TopicOut,
    TrackOut,
)
from adaptive_academy.engine.aliases import apply_program_aliases
from adaptive_academy.engine.curriculum import generate_curriculum
from adaptive_academy.engine.gates import evaluate_milestone_readonly, milestone_gate
from adaptive_academy.engine.memory import (
    index_accepted_sources,
    remove_source,
    sources_to_index,
)
from adaptive_academy.engine.research import (
    ResearchAlreadyDone,
    research_can_rerun,
    research_topic,
    strip_cite_tags,
)
from adaptive_academy.engine.revision import revision_suggested
from adaptive_academy.engine.topics import delete_topic
from adaptive_academy.engine.track_markdown import (
    DeliverableView,
    ItemView,
    PhaseView,
    SidebarView,
    TrackView,
    markdown_to_track,
    track_to_markdown,
)
from adaptive_academy.llm.researcher_types import ResearcherClient
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    Deliverable,
    Item,
    Milestone,
    Phase,
    Program,
    ProgramTopicLink,
    ReferenceAnchor,
    Sidebar,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
    Track,
)

router = APIRouter(prefix="/api/topics", tags=["topics"])


def _concepts_for(session: Session, topic_id: int) -> list[Concept]:
    return session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)
    ).all()


def _has_anchor(session: Session, concept_id: int) -> bool:
    return session.exec(
        select(ReferenceAnchor).where(ReferenceAnchor.concept_id == concept_id)).first() is not None


def _topic_out(session: Session, topic: Topic) -> TopicOut:
    concepts = _concepts_for(session, topic.id)
    intent = session.exec(
        select(TopicIntent).where(TopicIntent.topic_id == topic.id)
    ).first()
    has_foundation = (
        session.exec(
            select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)
        ).first()
        is not None
    )
    has_track = (
        session.exec(select(Track).where(Track.topic_id == topic.id)).first() is not None
    )
    return TopicOut(
        id=topic.id,
        title=topic.title,
        concepts=[
            ConceptOut(
                id=c.id, name=c.name, is_load_bearing=c.is_load_bearing,
                last_assessment_score=(
                    session.exec(
                        select(Assessment.score).where(Assessment.concept_id == c.id)
                        .order_by(Assessment.id.desc())
                    ).first()
                ),
                has_anchor=_has_anchor(session, c.id),
            )
            for c in concepts
        ],
        intent=IntentOut(
            goal=intent.goal,
            prior_knowledge=intent.prior_knowledge,
            time_budget=intent.time_budget,
        )
        if intent
        else None,
        has_foundation=has_foundation,
        has_track=has_track,
        research_running=is_running(f"research:{topic.id}"),
        can_research=not has_foundation or research_can_rerun(session, topic.id),
        is_demo=topic.is_demo,
    )


@router.get("", response_model=list[TopicOut])
def list_topics(session: Session = Depends(get_session)):
    topics = session.exec(select(Topic).order_by(Topic.id)).all()
    return [_topic_out(session, topic) for topic in topics]


@router.post("", response_model=TopicOut)
def create_topic(
    body: CreateTopicIn, session: Session = Depends(get_session)
) -> TopicOut:
    topic = Topic(title=body.title)
    session.add(topic)
    session.commit()
    session.refresh(topic)
    session.add(
        TopicIntent(
            topic_id=topic.id,
            goal=body.goal,
            prior_knowledge=body.prior_knowledge,
            time_budget=body.time_budget,
        )
    )
    session.commit()
    return _topic_out(session, topic)


@router.get("/{topic_id}", response_model=TopicOut)
def get_topic(topic_id: int, session: Session = Depends(get_session)):
    topic = session.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "topic not found")
    return _topic_out(session, topic)


@router.get("/{topic_id}/foundation", response_model=FoundationOut)
def get_foundation(
    topic_id: int, session: Session = Depends(get_session)
) -> FoundationOut:
    fnd = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)
    ).first()
    if fnd is None:
        raise HTTPException(status_code=404, detail="no foundation yet")
    return _foundation_out(fnd)


# Research strips web-search <cite> tags before storing; stripping again on the way out keeps
# rows stored before that fix readable.
def _foundation_out(fnd: TopicFoundation) -> FoundationOut:
    prereqs = fnd.prerequisite_map if isinstance(fnd.prerequisite_map, dict) else {}
    return FoundationOut(
        overview=strip_cite_tags(fnd.overview),
        key_concepts=[strip_cite_tags(c) for c in fnd.key_concepts],
        prerequisite_map={
            strip_cite_tags(k): [strip_cite_tags(x) if isinstance(x, str) else x for x in v]
            if isinstance(v, list) else v
            for k, v in prereqs.items()
        },
    )


def _source_out(s: SourceDoc) -> SourceDocOut:
    return SourceDocOut(
        id=s.id, title=strip_cite_tags(s.title), url=s.url, tier=s.tier,
        summary=strip_cite_tags(s.summary), why=strip_cite_tags(s.why), rank=s.rank,
        angle=s.angle, status=s.status,
    )


@router.post("/{topic_id}/research", response_model=ResearchOut)
def run_research(
    topic_id: int,
    session: Session = Depends(get_session),
    researcher: ResearcherClient = Depends(get_researcher),
    llm: LLMClient = Depends(get_llm),
    retriever: Retriever = Depends(get_retriever),
) -> ResearchOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="topic not found")
    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
    if intent is None:
        raise HTTPException(status_code=400, detail="topic has no intent")

    try:
        result = research_topic(
            session,
            topic,
            intent,
            researcher=researcher,
            llm=llm,
            retriever=retriever,
        )
    except (RunInProgress, ResearchAlreadyDone) as e:
        # Only these two are state conflicts. A ValueError here would swallow
        # json.JSONDecodeError (malformed model output), which has its own 502 handler.
        raise HTTPException(409, str(e)) from e
    return ResearchOut(
        foundation=_foundation_out(result.foundation),
        sources=[_source_out(s) for s in sorted(result.sources, key=lambda x: x.rank)],
        events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events],
    )


@router.get("/{topic_id}/events", response_model=list[EventOut])
def list_events(
    topic_id: int,
    session: Session = Depends(get_session),
) -> list[EventOut]:
    rows = session.exec(
        select(AgentEvent)
        .where(AgentEvent.topic_id == topic_id)
        .order_by(AgentEvent.id)
    ).all()
    return [EventOut(kind=e.kind, detail=e.detail, created_at=e.created_at) for e in rows]


@router.get("/{topic_id}/sources", response_model=list[SourceDocOut])
def list_sources(
    topic_id: int,
    status: Optional[str] = None,
    session: Session = Depends(get_session),
) -> list[SourceDocOut]:
    query = select(SourceDoc).where(SourceDoc.topic_id == topic_id)
    if status is not None:
        query = query.where(SourceDoc.status == status)
    rows = session.exec(query).all()
    rows.sort(key=lambda s: s.rank)
    return [_source_out(s) for s in rows]


@router.post("/{topic_id}/sources/review", response_model=list[SourceDocOut])
def review_sources(
    topic_id: int,
    body: ReviewSourcesIn,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    fetch: Callable[[str], str | None] = Depends(get_fetcher),
    retriever: Retriever = Depends(get_retriever),
) -> list[SourceDocOut]:
    """Save the reading list and return at once; accepted sources not indexed yet are fetched
    and indexed afterwards (index_accepted_sources), so no write lock spans a network fetch.

    Every accepted source with no chunks is queued, not only the ones accepted now: one whose
    earlier indexing never ran or failed (a crash, a fetch error, an empty page) is retried on
    the next save, unless its fetch failed in the last ten minutes. So is one with chunks the
    embedder never reached. A source a background task is already working on is not queued
    again (memory.sources_to_index). The task skips vault-backed ones."""
    rows = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic_id)).all()
    by_id = {s.id: s for s in rows}
    for sid in body.accepted_ids:
        if sid in by_id:
            by_id[sid].status = "accepted"
    for sid in body.pruned_ids:
        if sid in by_id:
            by_id[sid].status = "pruned"
    for source in rows:
        if source.status != "accepted" and source.id is not None:
            remove_source(session, f"sourcedoc:{source.id}")
    session.commit()
    to_index = sources_to_index(
        session, topic_id,
        [s.id for s in rows if s.status == "accepted" and s.id is not None],
        retriever=retriever,
    )
    if to_index:
        background.add_task(
            index_accepted_sources, session.get_bind(), to_index,
            fetch=fetch, retriever=retriever,
        )
    for s in rows:
        session.refresh(s)
    rows.sort(key=lambda s: s.rank)
    return [_source_out(s) for s in rows]


def _curriculum_out(session: Session, track: Track, events=None) -> CurriculumOut:
    phases = session.exec(
        select(Phase).where(Phase.track_id == track.id).order_by(Phase.position)
    ).all()
    phase_outs = []
    for p in phases:
        items = session.exec(
            select(Item).where(Item.phase_id == p.id).order_by(Item.position)
        ).all()
        deliverable = session.exec(
            select(Deliverable).where(Deliverable.phase_id == p.id)
        ).first()
        phase_outs.append(PhaseOut(
            id=p.id, title=p.title, position=p.position, est_hours=p.est_hours,
            flags=p.flags,
            items=[ItemOut(id=i.id, text=i.text, type=i.type, status=i.status,
                           position=i.position,
                           is_remediation=i.added_by == "remediation") for i in items],
            deliverable=DeliverableOut(id=deliverable.id, kind=deliverable.kind,
                                       text=deliverable.text,
                                       acceptance_criteria=deliverable.acceptance_criteria,
                                       artifact_url=deliverable.artifact_url,
                                       review_verdict=deliverable.review_verdict)
            if deliverable else None,
        ))
    sidebars = session.exec(
        select(Sidebar).where(Sidebar.track_id == track.id).order_by(Sidebar.position)
    ).all()
    concepts = session.exec(select(Concept).where(Concept.track_id == track.id)).all()
    return CurriculumOut(
        track=TrackOut(id=track.id, title=track.title, overview=track.overview),
        phases=phase_outs,
        sidebars=[SidebarOut(id=s.id, kind=s.kind, title=s.title, body=s.body,
                             position=s.position) for s in sidebars],
        concepts=[ConceptOut(id=c.id, name=c.name, is_load_bearing=c.is_load_bearing,
                             has_anchor=_has_anchor(session, c.id))
                  for c in concepts],
        events=[EventOut(kind=e.kind, detail=e.detail) for e in (events or [])],
    )


def _track_view(session: Session, track: Track) -> TrackView:
    phases = session.exec(
        select(Phase).where(Phase.track_id == track.id).order_by(Phase.position)
    ).all()
    pvs = []
    for p in phases:
        items = session.exec(
            select(Item).where(Item.phase_id == p.id).order_by(Item.position)
        ).all()
        d = session.exec(select(Deliverable).where(Deliverable.phase_id == p.id)).first()
        pvs.append(PhaseView(
            title=p.title, est_hours=p.est_hours, flags=p.flags,
            items=[ItemView(text=i.text, type=i.type, status=i.status) for i in items],
            deliverable=DeliverableView(text=d.text, kind=d.kind,
                                        acceptance_criteria=d.acceptance_criteria)
            if d else None,
        ))
    sidebars = session.exec(
        select(Sidebar).where(Sidebar.track_id == track.id).order_by(Sidebar.position)
    ).all()
    return TrackView(
        title=track.title, overview=track.overview, phases=pvs,
        sidebars=[SidebarView(kind=s.kind, title=s.title, body=s.body) for s in sidebars])


@router.post("/{topic_id}/curriculum", response_model=CurriculumOut)
def generate_curriculum_route(
    topic_id: int,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> CurriculumOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(404, "topic not found")
    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
    if intent is None:
        raise HTTPException(400, "topic has no intent")
    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)).first()
    if foundation is None:
        raise HTTPException(400, "topic has no foundation; run research first")
    accepted = session.exec(
        select(SourceDoc).where(SourceDoc.topic_id == topic_id,
                                SourceDoc.status == "accepted")).all()
    if not accepted:
        raise HTTPException(400, "no accepted sources; review the reading list first")
    accepted.sort(key=lambda s: s.rank)
    try:
        result = generate_curriculum(session, topic, intent, foundation, accepted, llm=llm)
    except RunInProgress as e:
        raise HTTPException(409, str(e)) from e
    apply_program_aliases(session, topic_id)
    return _curriculum_out(session, result.track, result.events)


@router.get("/{topic_id}/curriculum", response_model=CurriculumOut)
def get_curriculum(topic_id: int, session: Session = Depends(get_session)) -> CurriculumOut:
    track = session.exec(select(Track).where(Track.topic_id == topic_id)).first()
    if track is None:
        raise HTTPException(404, "no curriculum yet")
    return _curriculum_out(session, track)


@router.get("/{topic_id}/curriculum.md", response_class=PlainTextResponse)
def export_curriculum(topic_id: int, session: Session = Depends(get_session)) -> str:
    track = session.exec(select(Track).where(Track.topic_id == topic_id)).first()
    if track is None:
        raise HTTPException(404, "no curriculum yet")
    return track_to_markdown(_track_view(session, track))


@router.post("/{topic_id}/curriculum/import", response_model=CurriculumOut)
def import_curriculum(
    topic_id: int, body: ImportMarkdownIn, session: Session = Depends(get_session),
) -> CurriculumOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(404, "topic not found")
    view = markdown_to_track(body.markdown)
    # Policy: import replaces the track's phases/items/deliverables/sidebars ONLY.
    # Concepts, KnowledgeEstimates, ConceptAliases, Assessments and ConceptEdges are
    # competence evidence and graph history; they are never deleted by an import.
    # The oldest track is reused (title/overview updated); other tracks lose their
    # phase content and are removed only when they own no concepts.
    old = session.exec(select(Track).where(Track.topic_id == topic_id).order_by(Track.id)).all()
    track = None
    for old_track in old:
        for p in session.exec(select(Phase).where(Phase.track_id == old_track.id)).all():
            for it in session.exec(select(Item).where(Item.phase_id == p.id)).all():
                session.delete(it)
            d = session.exec(select(Deliverable).where(Deliverable.phase_id == p.id)).first()
            if d:
                session.delete(d)
            session.delete(p)
        for s in session.exec(select(Sidebar).where(Sidebar.track_id == old_track.id)).all():
            session.delete(s)
        if track is None:
            track = old_track
            track.title = view.title
            track.overview = view.overview
            session.add(track)
            continue
        owns_concepts = session.exec(
            select(Concept).where(Concept.track_id == old_track.id)
        ).first() is not None
        if not owns_concepts:
            session.delete(old_track)
    session.commit()

    if track is None:
        track = Track(topic_id=topic_id, title=view.title, overview=view.overview)
        session.add(track)
        session.commit()
        session.refresh(track)
    for pi, pv in enumerate(view.phases):
        phase = Phase(track_id=track.id, title=pv.title, position=pi,
                      est_hours=pv.est_hours, flags=pv.flags)
        session.add(phase)
        session.commit()
        session.refresh(phase)
        for ii, iv in enumerate(pv.items):
            session.add(Item(phase_id=phase.id, text=iv.text, type=iv.type,
                             status=iv.status, position=ii))
        if pv.deliverable:
            session.add(Deliverable(phase_id=phase.id, kind=pv.deliverable.kind,
                                    text=pv.deliverable.text,
                                    acceptance_criteria=pv.deliverable.acceptance_criteria))
    for si, sv in enumerate(view.sidebars):
        session.add(Sidebar(track_id=track.id, kind=sv.kind, title=sv.title,
                            body=sv.body, position=si))
    session.commit()
    session.refresh(track)
    # Markdown import creates no Concept rows (the format carries phases/items/sidebars
    # only, never concepts), so this is a no-op today. Called anyway for correctness and
    # so a program topic re-joins its alias groups the moment concepts do come from
    # import — it's a cheap no-op over zero concepts, not dead code.
    apply_program_aliases(session, topic_id)
    return _curriculum_out(session, track)


@router.get("/{topic_id}/program-context", response_model=Optional[ProgramContextOut])
def get_program_context(topic_id: int, session: Session = Depends(get_session)):
    # A standalone topic is the normal case, not an error: answer 200 with a null body so
    # every topic page can ask without logging a 404. Only an unknown topic id is a 404.
    if session.get(Topic, topic_id) is None:
        raise HTTPException(404, "topic not found")
    link = session.exec(
        select(ProgramTopicLink).where(ProgramTopicLink.topic_id == topic_id)
    ).first()
    if link is None:
        return None
    milestone = session.get(Milestone, link.milestone_id)
    program = session.get(Program, milestone.program_id) if milestone else None
    if milestone is None or program is None:
        return None
    # Archived milestones are excluded from gates (spec §4.3): milestone_gate WRITES
    # gate_status and can emit program:gate_passed on a transition, so an archived
    # milestone must never reach it — use the read-only evidence view instead, which
    # reports the milestone's stored gate_status as of archive time.
    report = (
        evaluate_milestone_readonly(session, milestone)
        if milestone.archived
        else milestone_gate(session, milestone)
    )
    return ProgramContextOut(
        program_id=program.id, program_title=program.title,
        milestone_id=milestone.id, milestone_title=milestone.title,
        gate_status=report.verdict,
        unverified=[e.name for e in report.concepts if e.verdict != "verified"],
        revision_suggested=revision_suggested(session, program))


@router.delete("/{topic_id}", status_code=204)
def delete_topic_route(topic_id: int, session: Session = Depends(get_session)) -> None:
    """Delete the topic and every row that belongs to it (demo topics too). A program slot it
    filled goes back to a stub; usage history and files in the vault are kept."""
    try:
        deleted = delete_topic(session, topic_id)
    except RunInProgress as e:
        raise HTTPException(409, "This topic is still being researched or planned. Wait for "
                                 "that to finish, then delete it.") from e
    if not deleted:
        raise HTTPException(404, "topic not found")
