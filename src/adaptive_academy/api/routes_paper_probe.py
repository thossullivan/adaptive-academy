from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import (
    PaperProbeAnswerIn, PaperProbeAnswerOut, PaperProbeAnswerRow, PaperProbeOut,
    PaperProbeStartIn, PaperQuestionRow, ScorecardRow,
)
from adaptive_academy.engine.gates import milestone_load_bearing
from adaptive_academy.engine.paper import PaperIngestError, ingest_paper
from adaptive_academy.engine.paper_probe import direct, grade_paper_probe
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    Assessment, Concept, Milestone, PaperProbe, PaperProbeAnswer,
)

router = APIRouter(tags=["paper_probe"])


def _public_questions(pp: PaperProbe) -> list[PaperQuestionRow]:
    return [PaperQuestionRow(index=q["index"], axis=q.get("axis", ""),
                             prompt=q.get("prompt", "")) for q in pp.questions]


def _answer_rows(session: Session, pid: int) -> list[PaperProbeAnswerRow]:
    rows = session.exec(
        select(PaperProbeAnswer).where(PaperProbeAnswer.probe_id == pid)
        .order_by(PaperProbeAnswer.question_index)).all()
    return [PaperProbeAnswerRow(question_index=a.question_index, content=a.content) for a in rows]


def _scorecard(session: Session, pid: int) -> list[ScorecardRow] | None:
    rows = session.exec(select(Assessment).where(Assessment.paper_probe_id == pid)).all()
    if not rows:
        return None
    out = []
    for a in rows:
        c = session.get(Concept, a.concept_id)
        out.append(ScorecardRow(concept_id=a.concept_id, concept=c.name if c else "",
                                score=a.score, verdict=a.verdict, gaps=list(a.gaps)))
    return out


def _out(session: Session, pp: PaperProbe) -> PaperProbeOut:
    return PaperProbeOut(
        probe_id=pp.id, program_id=pp.program_id, milestone_id=pp.milestone_id, status=pp.status,
        paper={"title": pp.paper_title, "url": pp.paper_url, "source": pp.source},
        questions=_public_questions(pp), answers=_answer_rows(session, pp.id),
        outcome=pp.outcome, scorecard=_scorecard(session, pp.id))


@router.post("/api/programs/{program_id}/milestones/{milestone_id}/paper-probe",
             response_model=PaperProbeOut)
def start_paper_probe(program_id: int, milestone_id: int, body: PaperProbeStartIn,
                      session: Session = Depends(get_session),
                      llm: LLMClient = Depends(get_llm)):
    milestone = session.get(Milestone, milestone_id)
    if milestone is None or milestone.program_id != program_id:
        raise HTTPException(404, "milestone not found")
    if not milestone_load_bearing(session, milestone):
        raise HTTPException(400, "start this milestone's topic first — no concepts to assess yet")
    try:
        extract = ingest_paper(url=body.url or None, pasted_text=body.pasted_text or None,
                               title=body.title or None)
    except PaperIngestError as e:
        raise HTTPException(400, str(e)) from e
    pp = PaperProbe(program_id=program_id, milestone_id=milestone_id, paper_title=extract.title,
                    paper_url=body.url or "", paper_text=extract.text, source=extract.source,
                    status="drafting")
    session.add(pp)
    session.commit()
    session.refresh(pp)
    direct(session, pp, llm=llm)
    return _out(session, pp)


def _probe_or_404(session: Session, pid: int) -> PaperProbe:
    pp = session.get(PaperProbe, pid)
    if pp is None:
        raise HTTPException(404, "paper probe not found")
    return pp


@router.get("/api/paper-probe/{pid}", response_model=PaperProbeOut)
def get_paper_probe(pid: int, session: Session = Depends(get_session)):
    return _out(session, _probe_or_404(session, pid))


@router.post("/api/paper-probe/{pid}/answers", response_model=PaperProbeAnswerOut)
def post_answer(pid: int, body: PaperProbeAnswerIn, session: Session = Depends(get_session)):
    pp = _probe_or_404(session, pid)
    if pp.status != "answering":
        raise HTTPException(400, f"probe is {pp.status}, not answering")
    existing = session.exec(select(PaperProbeAnswer).where(
        PaperProbeAnswer.probe_id == pid,
        PaperProbeAnswer.question_index == body.question_index)).first()
    if existing:
        existing.content = body.content
        session.add(existing)
    else:
        session.add(PaperProbeAnswer(probe_id=pid, question_index=body.question_index,
                                     content=body.content))
    session.commit()
    return PaperProbeAnswerOut(status=pp.status)


@router.post("/api/paper-probe/{pid}/submit", response_model=PaperProbeOut)
def submit_paper_probe(pid: int, session: Session = Depends(get_session),
                       llm: LLMClient = Depends(get_llm)):
    pp = _probe_or_404(session, pid)
    if pp.status not in ("answering", "graded"):
        raise HTTPException(400, f"probe is {pp.status}, not answering")
    grade_paper_probe(session, pp, llm=llm)  # idempotent — re-grade replaces prior evidence
    return _out(session, pp)


@router.get("/api/programs/{program_id}/milestones/{milestone_id}/paper-probe",
            response_model=list[PaperProbeOut])
def list_paper_probes(program_id: int, milestone_id: int,
                      session: Session = Depends(get_session)):
    rows = session.exec(select(PaperProbe).where(
        PaperProbe.milestone_id == milestone_id).order_by(PaperProbe.id.desc())).all()
    return [_out(session, pp) for pp in rows]
