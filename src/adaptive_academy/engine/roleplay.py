import json

from sqlmodel import Session

from adaptive_academy.engine.gates import milestone_load_bearing
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import AgentEvent, Milestone, RoleplaySession
from adaptive_academy.prompts import ROLEPLAY_DIRECTOR

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
