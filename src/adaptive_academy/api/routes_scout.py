"""Scout routes for evidence-backed Program topic suggestions."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import ScoutOut, TopicSuggestionOut
from adaptive_academy.engine.aliases import normalize_name
from adaptive_academy.engine.scout import _program_concept_keys, run_scout
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Milestone,
    Program,
    ProgramTopicLink,
    TopicSuggestion,
    now_utc,
)

router = APIRouter(tags=["scout"])


class AcceptSuggestionIn(BaseModel):
    milestone_id: int | None = None


def _program_or_404(session: Session, program_id: int) -> Program:
    program = session.get(Program, program_id)
    if program is None:
        raise HTTPException(404, "program not found")
    return program


def _suggestion_or_404(session: Session, suggestion_id: int) -> TopicSuggestion:
    suggestion = session.get(TopicSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(404, "suggestion not found")
    return suggestion


def _suggestion_out(suggestion: TopicSuggestion) -> TopicSuggestionOut:
    if suggestion.id is None or suggestion.program_id is None:
        raise ValueError("suggestion must belong to a program")
    return TopicSuggestionOut(
        id=suggestion.id,
        program_id=suggestion.program_id,
        title=suggestion.title,
        rationale=suggestion.rationale,
        candidate_kind=suggestion.candidate_kind,
        evidence=suggestion.evidence,
        score=suggestion.score,
        status=suggestion.status,
        created_at=suggestion.created_at,
        decided_at=suggestion.decided_at,
    )


def _require_proposed(suggestion: TopicSuggestion) -> None:
    if suggestion.status != "proposed":
        raise HTTPException(409, f"suggestion already {suggestion.status}")


@router.post("/api/programs/{program_id}/scout", response_model=ScoutOut)
def scout_program(
    program_id: int,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> ScoutOut:
    program = _program_or_404(session, program_id)
    result = run_scout(session, program, llm=llm)
    return ScoutOut(
        suggestions=[_suggestion_out(item) for item in result.suggestions],
        candidates=result.counts,
        truncated=result.truncated,
    )


@router.get(
    "/api/programs/{program_id}/suggestions",
    response_model=list[TopicSuggestionOut],
)
def list_suggestions(
    program_id: int,
    status: str | None = None,
    session: Session = Depends(get_session),
) -> list[TopicSuggestionOut]:
    _program_or_404(session, program_id)
    statement = select(TopicSuggestion).where(
        TopicSuggestion.program_id == program_id
    )
    if status is not None:
        statement = statement.where(TopicSuggestion.status == status)
    suggestions = session.exec(
        statement.order_by(TopicSuggestion.score.desc(), TopicSuggestion.id)
    ).all()
    return [_suggestion_out(item) for item in suggestions]


@router.post(
    "/api/suggestions/{suggestion_id}/accept",
    response_model=TopicSuggestionOut,
)
def accept_suggestion(
    suggestion_id: int,
    body: AcceptSuggestionIn | None = None,
    session: Session = Depends(get_session),
) -> TopicSuggestionOut:
    suggestion = _suggestion_or_404(session, suggestion_id)
    _require_proposed(suggestion)
    if suggestion.program_id is None or body is None or body.milestone_id is None:
        raise HTTPException(400, "a valid program milestone is required")
    if normalize_name(suggestion.title) in _program_concept_keys(session, suggestion.program_id):
        raise HTTPException(409, "a concept with this name already exists")
    milestone = session.get(Milestone, body.milestone_id)
    if (
        milestone is None
        or milestone.program_id != suggestion.program_id
        or milestone.archived
    ):
        raise HTTPException(400, "a valid program milestone is required")

    session.add(
        ProgramTopicLink(
            milestone_id=milestone.id,
            status="stub",
            proposed_title=suggestion.title,
            why=suggestion.rationale,
            added_by="scout",
        )
    )
    suggestion.status = "accepted"
    suggestion.decided_at = now_utc()
    session.add(suggestion)
    session.add(
        AgentEvent(
            program_id=suggestion.program_id,
            kind="scout:accepted",
            detail=f"suggestion {suggestion.id}, milestone {milestone.id}",
        )
    )
    session.commit()
    session.refresh(suggestion)
    return _suggestion_out(suggestion)


@router.post(
    "/api/suggestions/{suggestion_id}/dismiss",
    response_model=TopicSuggestionOut,
)
def dismiss_suggestion(
    suggestion_id: int,
    session: Session = Depends(get_session),
) -> TopicSuggestionOut:
    suggestion = _suggestion_or_404(session, suggestion_id)
    _require_proposed(suggestion)
    if suggestion.program_id is None:
        raise HTTPException(400, "suggestion does not belong to a program")
    suggestion.status = "dismissed"
    suggestion.decided_at = now_utc()
    session.add(suggestion)
    session.add(
        AgentEvent(
            program_id=suggestion.program_id,
            kind="scout:dismissed",
            detail=f"suggestion {suggestion.id}",
        )
    )
    session.commit()
    session.refresh(suggestion)
    return _suggestion_out(suggestion)
