import json

from sqlmodel import select

from adaptive_academy.prompts import (
    ROLEPLAY_DIRECTOR, ROLEPLAY_PERSONA, ROLEPLAY_GRADE, build_roleplay_persona_prompt,
)
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.models import (
    Program, Milestone, Track, Topic, Concept, KnowledgeEstimate,
    ProgramTopicLink, RoleplaySession, RoleplayTurn,
)
from adaptive_academy.engine.roleplay import direct, run_roleplay_turn


def test_prompts_have_tags():
    assert ROLEPLAY_DIRECTOR.tag == "roleplay.director@v1"
    assert ROLEPLAY_PERSONA.tag == "roleplay.persona@v1"
    assert ROLEPLAY_GRADE.tag == "roleplay.grade@v1"


def test_persona_prompt_embeds_brief_and_hides_grading():
    brief = {"persona": "Skeptical VP of Engineering", "goal": "avoid committing",
             "situation": "a cold outbound call", "hidden_objections": ["already have a vendor"],
             "win_conditions": ["agree to a technical eval"], "difficulty": "high"}
    text = build_roleplay_persona_prompt(brief)
    assert "Skeptical VP of Engineering" in text
    assert "cold outbound call" in text
    assert "[[END]]" in text  # end-signal instruction present
    # The persona must not be told to grade or reveal internals.
    assert "score" not in text.lower()


def _materialized_milestone(s):
    p = Program(title="B2B Sales", goal_statement="g"); s.add(p); s.commit(); s.refresh(p)
    m = Milestone(program_id=p.id, title="Discovery", success_criteria="run a discovery call")
    s.add(m); s.commit(); s.refresh(m)
    t = Topic(title="Discovery"); s.add(t); s.commit(); s.refresh(t)
    tr = Track(topic_id=t.id, title="tr"); s.add(tr); s.commit(); s.refresh(tr)
    c = Concept(track_id=tr.id, name="SPIN questioning", is_load_bearing=True)
    s.add(c); s.commit(); s.refresh(c)
    s.add(KnowledgeEstimate(concept_id=c.id, level="low")); s.commit()
    s.add(ProgramTopicLink(milestone_id=m.id, topic_id=t.id, status="started")); s.commit()
    return p, m


def test_direct_fills_brief_and_activates(session):
    p, m = _materialized_milestone(session)
    rp = RoleplaySession(program_id=p.id, milestone_id=m.id, status="briefing")
    session.add(rp); session.commit(); session.refresh(rp)
    brief = {"persona": "VP Eng", "goal": "resist", "situation": "cold call",
             "hidden_objections": ["price"], "win_conditions": ["demo"], "difficulty": "low"}
    llm = ScriptedLLMClient([LLMResponse(text=json.dumps(brief))])
    out = direct(session, rp, llm=llm)
    assert out.status == "active"
    assert out.persona_brief["persona"] == "VP Eng"
    # the concept name should have been included in the director's prompt
    assert "SPIN questioning" in llm.calls[0]["messages"][0]["content"]


def _active_session(s):
    p, m = _materialized_milestone(s)
    rp = RoleplaySession(program_id=p.id, milestone_id=m.id, status="active",
                         persona_brief={"persona": "VP", "goal": "resist", "situation": "call",
                                        "hidden_objections": [], "win_conditions": [],
                                        "difficulty": "low"})
    s.add(rp); s.commit(); s.refresh(rp)
    return rp


def test_turn_persists_pair_and_stays_active(session):
    rp = _active_session(session)
    llm = ScriptedLLMClient([LLMResponse(text="Who is this?")])
    res = run_roleplay_turn(session, rp, "Hi, calling about X", llm=llm)
    assert res.reply == "Who is this?" and res.status == "active"
    turns = session.exec(select(RoleplayTurn).where(RoleplayTurn.session_id == rp.id)
                         .order_by(RoleplayTurn.id)).all()
    assert [(t.role, t.content) for t in turns] == [
        ("user", "Hi, calling about X"), ("persona", "Who is this?")]


def test_end_signal_strips_token_and_ends(session):
    rp = _active_session(session)
    llm = ScriptedLLMClient([LLMResponse(text="Fine, book the demo. [[END]]")])
    res = run_roleplay_turn(session, rp, "Let me show you", llm=llm)
    assert res.status == "ended"
    assert res.reply == "Fine, book the demo."
    session.refresh(rp)
    assert rp.status == "ended"


def test_turn_cap_ends_session(session):
    rp = _active_session(session)
    # Pre-seed 14 prior user turns; the 15th should trip the cap.
    for i in range(14):
        session.add(RoleplayTurn(session_id=rp.id, role="user", content=f"u{i}"))
    session.commit()
    llm = ScriptedLLMClient([LLMResponse(text="Still not interested.")])
    res = run_roleplay_turn(session, rp, "one more thing", llm=llm)
    assert res.status == "ended"
