import json
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.engine.gates import milestone_load_bearing
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import AgentEvent, Milestone, RoleplaySession, RoleplayTurn
from adaptive_academy.prompts import ROLEPLAY_DIRECTOR, ROLEPLAY_PERSONA, build_roleplay_persona_prompt

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
    session.add(RoleplayTurn(session_id=rp.id, role="user", content=user_text))
    session.commit()

    system = build_roleplay_persona_prompt(rp.persona_brief)
    _emit(session, rp, "prompt", ROLEPLAY_PERSONA.tag)
    resp = llm.complete(system=system, messages=_history(session, rp), tools=[])

    reply = resp.text
    ended = False
    if _END in reply:
        reply = reply.replace(_END, "").strip()
        ended = True

    session.add(RoleplayTurn(session_id=rp.id, role="persona", content=reply))

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
