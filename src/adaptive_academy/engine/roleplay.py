import json
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.engine.assess import assess_concept
from adaptive_academy.engine.gates import milestone_load_bearing
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.memory import (
    index_question,
    index_roleplay_turn,
    remove_source,
    topic_id_for_concept,
)
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent, Assessment, Milestone, RoleplaySession, RoleplayTurn,
)
from adaptive_academy.prompts import (
    ROLEPLAY_DIRECTOR, ROLEPLAY_GRADE, ROLEPLAY_PERSONA, build_roleplay_persona_prompt,
)

_TURN_CAP = 15
_END = "[[END]]"


def _emit(session: Session, rp: RoleplaySession, kind: str, detail: str = "") -> None:
    session.add(AgentEvent(program_id=rp.program_id, roleplay_session_id=rp.id,
                           kind=kind, detail=detail))


def direct(session: Session, rp: RoleplaySession, *, llm: LLMClient) -> RoleplaySession:
    """Generate the persona brief from the milestone + load-bearing concepts; activate."""
    milestone = session.get(Milestone, rp.milestone_id)
    concepts = milestone_load_bearing(session, milestone)
    lines = [f"MILESTONE: {milestone.title}", f"SUCCESS CRITERIA: {milestone.success_criteria}",
             "", "LOAD-BEARING CONCEPTS (name — learner level):"]
    for c in concepts:
        level = compute_levels(c.estimate)
        lines.append(f"- {c.name} — challenge={level.challenge}")
    user = "<<<MILESTONE>>>\n" + "\n".join(lines) + "\n<<<END_MILESTONE>>>"

    _emit(session, rp, "prompt", ROLEPLAY_DIRECTOR.tag)
    resp = llm.complete(system=ROLEPLAY_DIRECTOR,
                        messages=[{"role": "user", "content": user}], tools=[])
    brief = json.loads(extract_json(resp.text))
    rp.persona_brief = brief
    rp.status = "active"
    _emit(session, rp, "roleplay:brief", brief.get("persona", ""))
    session.add(rp)
    concept_ids = [concept.id for concept in concepts if concept.id is not None]
    topic_id = topic_id_for_concept(session, concept_ids[0]) if concept_ids else None
    index_question(
        session,
        text=str(brief.get("situation", "")),
        source_ref=f"roleplaysession:{rp.id}#opening",
        topic_id=topic_id,
        concept_id=concept_ids[0] if len(concept_ids) == 1 else None,
    )
    session.commit()
    session.refresh(rp)
    return rp


@dataclass
class TurnResult:
    reply: str
    status: str


def _history(session: Session, rp: RoleplaySession) -> list[dict]:
    role_map = {"user": "user", "persona": "assistant"}
    turns = session.exec(
        select(RoleplayTurn).where(RoleplayTurn.session_id == rp.id).order_by(RoleplayTurn.id)
    ).all()
    return [{"role": role_map[t.role], "content": t.content} for t in turns]


def run_roleplay_turn(session: Session, rp: RoleplaySession, user_text: str, *,
                      llm: LLMClient) -> TurnResult:
    milestone = session.get(Milestone, rp.milestone_id)
    concepts = milestone_load_bearing(session, milestone)
    concept_ids = [concept.id for concept in concepts if concept.id is not None]
    topic_id = topic_id_for_concept(session, concept_ids[0]) if concept_ids else None

    user_turn = RoleplayTurn(session_id=rp.id, role="user", content=user_text)
    session.add(user_turn)
    session.flush()
    index_roleplay_turn(
        session,
        user_turn,
        topic_id=topic_id,
        concept_ids=concept_ids,
    )
    session.commit()

    system = build_roleplay_persona_prompt(rp.persona_brief)
    _emit(session, rp, "prompt", ROLEPLAY_PERSONA.tag)
    resp = llm.complete(system=system, messages=_history(session, rp), tools=[])

    reply = resp.text
    ended = False
    if _END in reply:
        reply = reply.replace(_END, "").strip()
        ended = True

    persona_turn = RoleplayTurn(session_id=rp.id, role="persona", content=reply)
    session.add(persona_turn)
    session.flush()
    index_roleplay_turn(
        session,
        persona_turn,
        topic_id=topic_id,
        concept_ids=concept_ids,
    )

    user_turns = len(session.exec(
        select(RoleplayTurn).where(RoleplayTurn.session_id == rp.id,
                                   RoleplayTurn.role == "user")).all())
    if user_turns >= _TURN_CAP:
        ended = True

    if ended:
        rp.status = "ended"
        _emit(session, rp, "roleplay:ended")
        session.add(rp)
    session.commit()
    session.refresh(rp)
    return TurnResult(reply=reply, status=rp.status)


def _transcript_text(session: Session, rp: RoleplaySession) -> str:
    turns = session.exec(
        select(RoleplayTurn).where(RoleplayTurn.session_id == rp.id).order_by(RoleplayTurn.id)
    ).all()
    speaker = {"user": "LEARNER", "persona": "PERSONA"}
    return "\n".join(f"{speaker[t.role]}: {t.content}" for t in turns)


def grade_roleplay(session: Session, rp: RoleplaySession, *, llm: LLMClient) -> list[Assessment]:
    """Blind grade: reuse assess_concept per load-bearing concept, then write an outcome."""
    milestone = session.get(Milestone, rp.milestone_id)
    concepts = milestone_load_bearing(session, milestone)
    transcript = _transcript_text(session, rp)

    # Idempotent re-grade (a prior grade may have partially written then failed): clear any
    # existing roleplay evidence for this session so retries never double-count.
    for old in session.exec(
            select(Assessment).where(Assessment.roleplay_session_id == rp.id)).all():
        remove_source(session, f"assessment:{old.id}#q")
        remove_source(session, f"assessment:{old.id}#r")
        session.delete(old)

    graded: list[Assessment] = []
    for c in concepts:
        result = assess_concept(session, c, "roleplay", transcript, llm=llm)
        result.assessment.roleplay_session_id = rp.id
        session.add(result.assessment)
        graded.append(result.assessment)

    _emit(session, rp, "prompt", ROLEPLAY_GRADE.tag)
    user = "<<<TRANSCRIPT>>>\n" + transcript + "\n<<<END_TRANSCRIPT>>>"
    resp = llm.complete(system=ROLEPLAY_GRADE,
                        messages=[{"role": "user", "content": user}], tools=[])
    rp.outcome = json.loads(extract_json(resp.text))
    rp.status = "graded"
    _emit(session, rp, "roleplay:graded", f"{len(graded)} concept(s)")
    session.add(rp)
    session.commit()
    for a in graded:
        session.refresh(a)
    session.refresh(rp)
    return graded
