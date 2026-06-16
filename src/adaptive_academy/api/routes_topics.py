from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_llm, get_researcher, get_session
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
    ResearchOut,
    ReviewSourcesIn,
    SidebarOut,
    SourceDocOut,
    TopicOut,
    TrackOut,
)
from adaptive_academy.engine.curriculum import generate_curriculum
from adaptive_academy.engine.research import research_topic
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
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Concept,
    Deliverable,
    Item,
    Phase,
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
            ConceptOut(id=c.id, name=c.name, is_load_bearing=c.is_load_bearing)
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
    )


@router.get("", response_model=list[TopicOut])
def list_topics(session: Session = Depends(get_session)):
    return [_topic_out(session, topic) for topic in session.exec(select(Topic)).all()]


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
    return FoundationOut(
        overview=fnd.overview,
        key_concepts=fnd.key_concepts,
        prerequisite_map=fnd.prerequisite_map,
    )


def _source_out(s: SourceDoc) -> SourceDocOut:
    return SourceDocOut(
        id=s.id, title=s.title, url=s.url, tier=s.tier, summary=s.summary,
        why=s.why, rank=s.rank, angle=s.angle, status=s.status,
    )


@router.post("/{topic_id}/research", response_model=ResearchOut)
def run_research(
    topic_id: int,
    session: Session = Depends(get_session),
    researcher: ResearcherClient = Depends(get_researcher),
    llm: LLMClient = Depends(get_llm),
) -> ResearchOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="topic not found")
    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
    if intent is None:
        raise HTTPException(status_code=400, detail="topic has no intent")

    result = research_topic(session, topic, intent, researcher=researcher, llm=llm)
    return ResearchOut(
        foundation=FoundationOut(
            overview=result.foundation.overview,
            key_concepts=result.foundation.key_concepts,
            prerequisite_map=result.foundation.prerequisite_map,
        ),
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
    return [EventOut(kind=e.kind, detail=e.detail) for e in rows]


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
    session: Session = Depends(get_session),
) -> list[SourceDocOut]:
    rows = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic_id)).all()
    by_id = {s.id: s for s in rows}
    for sid in body.accepted_ids:
        if sid in by_id:
            by_id[sid].status = "accepted"
    for sid in body.pruned_ids:
        if sid in by_id:
            by_id[sid].status = "pruned"
    session.commit()
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
                           position=i.position) for i in items],
            deliverable=DeliverableOut(id=deliverable.id, kind=deliverable.kind,
                                       text=deliverable.text,
                                       acceptance_criteria=deliverable.acceptance_criteria)
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
        concepts=[ConceptOut(id=c.id, name=c.name, is_load_bearing=c.is_load_bearing)
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
    result = generate_curriculum(session, topic, intent, foundation, accepted, llm=llm)
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
    # Replace any existing track for this topic.
    old = session.exec(select(Track).where(Track.topic_id == topic_id)).all()
    for t in old:
        for p in session.exec(select(Phase).where(Phase.track_id == t.id)).all():
            for it in session.exec(select(Item).where(Item.phase_id == p.id)).all():
                session.delete(it)
            d = session.exec(select(Deliverable).where(Deliverable.phase_id == p.id)).first()
            if d:
                session.delete(d)
            session.delete(p)
        for s in session.exec(select(Sidebar).where(Sidebar.track_id == t.id)).all():
            session.delete(s)
        session.delete(t)
    session.commit()

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
    return _curriculum_out(session, track)
