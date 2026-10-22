from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_llm, get_retriever, get_session
from adaptive_academy.api.schemas import (
    RoleplaySessionOut, RoleplayTurnIn, RoleplayTurnOut, RoleplayTurnRow, ScorecardRow,
)
from adaptive_academy.engine.gates import milestone_load_bearing
from adaptive_academy.engine.roleplay import direct, grade_roleplay, run_roleplay_turn
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    Assessment, Concept, Milestone, RoleplaySession, RoleplayTurn,
)

router = APIRouter(tags=["roleplay"])


def _public_brief(brief: dict) -> dict:
    return {"persona": brief.get("persona", ""), "situation": brief.get("situation", "")}


def _turns(session: Session, sid: int) -> list[RoleplayTurnRow]:
    rows = session.exec(
        select(RoleplayTurn).where(RoleplayTurn.session_id == sid).order_by(RoleplayTurn.id)
    ).all()
    return [RoleplayTurnRow(role=t.role, content=t.content) for t in rows]


def _scorecard(session: Session, sid: int) -> list[ScorecardRow] | None:
    rows = session.exec(select(Assessment).where(Assessment.roleplay_session_id == sid)).all()
    if not rows:
        return None
    out = []
    for a in rows:
        c = session.get(Concept, a.concept_id)
        out.append(ScorecardRow(concept_id=a.concept_id, concept=c.name if c else "",
                                score=a.score, verdict=a.verdict, gaps=list(a.gaps),
                                prompt_tag=a.prompt_tag))
    return out


def _out(session: Session, rp: RoleplaySession) -> RoleplaySessionOut:
    return RoleplaySessionOut(
        session_id=rp.id, program_id=rp.program_id, status=rp.status,
        brief_public=_public_brief(rp.persona_brief),
        turns=_turns(session, rp.id), outcome=rp.outcome, scorecard=_scorecard(session, rp.id))


@router.post("/api/programs/{program_id}/milestones/{milestone_id}/roleplay",
             response_model=RoleplaySessionOut)
def start_roleplay(program_id: int, milestone_id: int,
                   session: Session = Depends(get_session),
                   llm: LLMClient = Depends(get_llm),
                   retriever: Retriever = Depends(get_retriever)):
    milestone = session.get(Milestone, milestone_id)
    if milestone is None or milestone.program_id != program_id:
        raise HTTPException(404, "milestone not found")
    if not milestone_load_bearing(session, milestone):
        raise HTTPException(400, "start this milestone's topic first — no concepts to assess yet")
    rp = RoleplaySession(program_id=program_id, milestone_id=milestone_id, status="briefing")
    session.add(rp)
    session.commit()
    session.refresh(rp)
    direct(session, rp, llm=llm, retriever=retriever)
    return _out(session, rp)


def _session_or_404(session: Session, sid: int) -> RoleplaySession:
    rp = session.get(RoleplaySession, sid)
    if rp is None:
        raise HTTPException(404, "roleplay session not found")
    return rp


@router.get("/api/roleplay/{sid}", response_model=RoleplaySessionOut)
def get_roleplay(sid: int, session: Session = Depends(get_session)):
    return _out(session, _session_or_404(session, sid))


@router.post("/api/roleplay/{sid}/turns", response_model=RoleplayTurnOut)
def post_turn(sid: int, body: RoleplayTurnIn, session: Session = Depends(get_session),
              llm: LLMClient = Depends(get_llm),
              retriever: Retriever = Depends(get_retriever)):
    rp = _session_or_404(session, sid)
    if rp.status != "active":
        raise HTTPException(400, f"session is {rp.status}, not active")
    res = run_roleplay_turn(
        session,
        rp,
        body.content,
        llm=llm,
        retriever=retriever,
    )
    return RoleplayTurnOut(reply=res.reply, status=res.status, recorded=res.recorded)


@router.post("/api/roleplay/{sid}/end", response_model=RoleplaySessionOut)
def end_roleplay(sid: int, session: Session = Depends(get_session),
                 llm: LLMClient = Depends(get_llm),
                 retriever: Retriever = Depends(get_retriever)):
    rp = _session_or_404(session, sid)
    if rp.status == "graded":
        return _out(session, rp)  # idempotent
    if rp.status == "active":
        rp.status = "ended"
        session.add(rp)
        session.commit()
        session.refresh(rp)
    grade_roleplay(session, rp, llm=llm, retriever=retriever)
    return _out(session, rp)


@router.get("/api/programs/{program_id}/milestones/{milestone_id}/roleplay",
            response_model=list[RoleplaySessionOut])
def list_roleplays(program_id: int, milestone_id: int,
                   session: Session = Depends(get_session)):
    rows = session.exec(select(RoleplaySession).where(
        RoleplaySession.milestone_id == milestone_id).order_by(RoleplaySession.id.desc())).all()
    return [_out(session, rp) for rp in rows]
