"""Every grader runs its answer through named output checks before anything is written.

Per grader, with the scripted client (no live calls):
  good            → one call, no regeneration, the row is written;
  bad then good   → exactly one regeneration, sent as an APPEND-ONLY correction turn naming
                    the failed rule id (the original turn is never edited), and a correct row;
  bad twice       → GradeCheckError (`invalid_output`), no Assessment row, no estimate change,
                    no outcome/verdict change, prior evidence intact, the rejection traced;
  over HTTP       → 502 with category `invalid_output`, learning record unchanged.
"""

import json
from dataclasses import dataclass
from typing import Callable

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.engine.artifact import review_artifact
from adaptive_academy.engine.assess import assess_concept
from adaptive_academy.engine.decay import grade_decay_check, schedule_decay_check
from adaptive_academy.engine.output_checks import GradeCheckError, GRADE_RUBRIC, check_output
from adaptive_academy.engine.paper_probe import grade_paper_probe
from adaptive_academy.engine.productive_failure import consolidate
from adaptive_academy.engine.roleplay import grade_roleplay
from adaptive_academy.engine.teach import grade_teaching
from adaptive_academy.llm.errors import classify_llm_error
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse, StructuredOutputError
from adaptive_academy.models import (
    AgentEvent, Assessment, Concept, Deliverable, Item, KnowledgeEstimate, Milestone,
    PaperProbe, PaperProbeAnswer, Phase, Program, ProgramTopicLink, RecallPrompt,
    RoleplaySession, RoleplayTurn, Rubric, Topic, Track,
)
from adaptive_academy.prompts import (
    ASSESS_ARTIFACT, grade_prompt, GRADE_CORRECTION, PF_CONSOLIDATE, TEACH, Prompt,
)

_NONE_NAMED = {"missing_required": [], "misconceptions_committed": []}  # GRADE v6 fields
GOOD_GRADE = json.dumps({"score": 0.7, "mechanism_present": True, "verdict": "solid",
                         "gaps": ["masking left vague"], **_NONE_NAMED})
BAD_GRADE = json.dumps({"score": 7, "mechanism_present": True, "verdict": "solid",
                        "gaps": ["masking left vague"], **_NONE_NAMED})  # G1: a 0..10 score
BAD_GRADE_MECH = json.dumps({"score": 0.9, "mechanism_present": "false", "verdict": "fluent",
                             "gaps": [], **_NONE_NAMED})  # G5: bool("false") would skip the cap
GOOD_TEACH = json.dumps({"score": 0.75, "feedback": "clear", "strengths": ["example"],
                         "gaps": ["why sqrt(d)"]})
BAD_TEACH = json.dumps({"score": 0.75, "strengths": ["example"], "gaps": []})  # F1
GOOD_PF = json.dumps({"canonical": "scale by 1/sqrt(d)", "feedback": "saw the variance",
                      "score": 0.7})
BAD_PF = json.dumps({"canonical": "", "feedback": "good start", "score": 0.7})  # P1
GOOD_OUTCOME = json.dumps({"result": "demo booked", "summary": "Surfaced the objection."})
BAD_OUTCOME = "The learner did fine."  # J1


@dataclass
class World:
    program: Program
    milestone: Milestone
    c1: Concept
    c2: Concept
    deliverable: Deliverable
    rp: RoleplaySession
    pp: PaperProbe


def _add(s, obj):
    s.add(obj)
    s.commit()
    s.refresh(obj)
    return obj


def _world(s) -> World:
    p = _add(s, Program(title="P", goal_statement="g"))
    m = _add(s, Milestone(program_id=p.id, title="M", success_criteria="dissect"))
    t = _add(s, Topic(title="Transformers"))
    tr = _add(s, Track(topic_id=t.id, title="tr"))
    c1 = _add(s, Concept(track_id=tr.id, name="self-attention", is_load_bearing=True))
    c2 = _add(s, Concept(track_id=tr.id, name="positional encoding", is_load_bearing=True))
    for c in (c1, c2):
        s.add(KnowledgeEstimate(concept_id=c.id, level="medium", confidence=0.5))
        s.add(Rubric(concept_id=c.id, criteria=["mechanism"], must_include=[], weak_signs=[]))
    s.add(ProgramTopicLink(milestone_id=m.id, topic_id=t.id, status="started"))
    phase = _add(s, Phase(track_id=tr.id, title="Attention", position=0))
    s.add(Item(phase_id=phase.id, type="build", text="build it", concept_refs=[c1.name]))
    d = _add(s, Deliverable(phase_id=phase.id, kind="repo", text="attention.py",
                            acceptance_criteria=["implements scaled dot-product"]))
    rp = _add(s, RoleplaySession(program_id=p.id, milestone_id=m.id, status="ended",
                                 persona_brief={"persona": "VP"}))
    s.add(RoleplayTurn(session_id=rp.id, role="user", content="Why does attention scale?"))
    s.add(RoleplayTurn(session_id=rp.id, role="persona", content="Convince me."))
    pp = _add(s, PaperProbe(
        program_id=p.id, milestone_id=m.id, paper_title="AIAYN", paper_text="We propose...",
        status="answering",
        questions=[{"index": 0, "axis": "method", "prompt": "How?", "concept_ids": [c1.id]},
                   {"index": 1, "axis": "assumption", "prompt": "Why?",
                    "concept_ids": [c2.id]}]))
    s.add(PaperProbeAnswer(probe_id=pp.id, question_index=0, content="QKV..."))
    s.add(PaperProbeAnswer(probe_id=pp.id, question_index=1, content="Sinusoids..."))
    s.commit()
    return World(p, m, c1, c2, d, rp, pp)


def _learning_state(s, w: World) -> dict:
    """Everything a grade may change. A rejected grade must leave all of it untouched."""
    s.expire_all()
    rp, pp, d = s.get(RoleplaySession, w.rp.id), s.get(PaperProbe, w.pp.id), \
        s.get(Deliverable, w.deliverable.id)
    return {
        "assessments": sorted((a.id, a.kind, a.score) for a in s.exec(select(Assessment))),
        "estimates": sorted((e.concept_id, e.level, e.confidence)
                            for e in s.exec(select(KnowledgeEstimate))),
        "deliverable": (d.review_verdict, d.artifact_url),
        "roleplay": (rp.status, rp.outcome),
        "paper_probe": (pp.status, pp.outcome),
        "recall": sorted((r.id, r.due_at, r.last_result) for r in s.exec(select(RecallPrompt))),
    }


def _kinds(s) -> list[str]:
    return [e.kind for e in s.exec(select(AgentEvent).order_by(AgentEvent.id))]


def _events(s, kind: str) -> list[AgentEvent]:
    return s.exec(select(AgentEvent).where(AgentEvent.kind == kind)
                  .order_by(AgentEvent.id)).all()


# ── Grader table ─────────────────────────────────────────────────────────────

def _run_assess(s, w, llm):
    assess_concept(s, w.c1, "self_explanation", "attention weighs values", llm=llm)


def _run_teach(s, w, llm):
    grade_teaching(s, w.c1, "Attention is a soft lookup...", llm=llm)


def _run_consolidate(s, w, llm):
    consolidate(s, w.c1, "a problem", "my attempt", llm=llm)


def _run_artifact(s, w, llm):
    review_artifact(s, w.deliverable, "https://example.invalid/repo", "code", llm=llm,
                    fetch=lambda _url: None)


def _run_decay(s, w, llm):
    prompt = schedule_decay_check(s, w.c1.id)
    grade_decay_check(s, prompt.id, "from memory: attention...", llm=llm)


def _run_roleplay(s, w, llm):
    grade_roleplay(s, w.rp, llm=llm)


def _run_paper_probe(s, w, llm):
    grade_paper_probe(s, w.pp, llm=llm)


@dataclass
class Grader:
    run: Callable
    steps: list[tuple[str, str, str]]  # per model call: (good answer, bad answer, failed id)
    rows: int  # Assessment rows a good run writes
    score: float  # the score those rows get
    prompt: Prompt  # the grader prompt whose tag those rows carry


GRADERS = {
    "assess": Grader(_run_assess, [(GOOD_GRADE, BAD_GRADE, "G1")], 1, 0.7, grade_prompt()),
    "teach": Grader(_run_teach, [(GOOD_TEACH, BAD_TEACH, "F1")], 1, 0.75, TEACH),
    "consolidate": Grader(_run_consolidate, [(GOOD_PF, BAD_PF, "P1")], 1, 0.7,
                          PF_CONSOLIDATE),
    "artifact": Grader(_run_artifact, [(GOOD_GRADE, BAD_GRADE_MECH, "G5")], 1, 0.7,
                       ASSESS_ARTIFACT),
    "decay": Grader(_run_decay, [(GOOD_GRADE, BAD_GRADE_MECH, "G5")], 1, 0.7, grade_prompt()),
    # Multi-step graders: step i < 2 grades concept c1 / c2 (one row each); step 2 is the
    # debrief, which writes no row.
    "roleplay": Grader(_run_roleplay, [(GOOD_GRADE, BAD_GRADE, "G1"),
                                       (GOOD_GRADE, BAD_GRADE_MECH, "G5"),
                                       (GOOD_OUTCOME, BAD_OUTCOME, "J1")], 2, 0.7, grade_prompt()),
    "paper_probe": Grader(_run_paper_probe, [(GOOD_GRADE, BAD_GRADE, "G1"),
                                             (GOOD_GRADE, BAD_GRADE, "G1"),
                                             (GOOD_OUTCOME, BAD_OUTCOME, "J1")], 2, 0.7, grade_prompt()),
}
STEP_CASES = [(name, i) for name, g in GRADERS.items() for i in range(len(g.steps))]


def _goods(g: Grader) -> list[str]:
    return [good for good, _bad, _rid in g.steps]


def _script(texts: list[str | LLMResponse]) -> ScriptedLLMClient:
    return ScriptedLLMClient(
        [t if isinstance(t, LLMResponse) else LLMResponse(text=t) for t in texts])


def _row_tags(session) -> list[str]:
    """prompt_tag per Assessment row, in concept order (c1 before c2)."""
    rows = session.exec(select(Assessment).order_by(Assessment.concept_id)).all()
    return [a.prompt_tag for a in rows]


@pytest.mark.parametrize("name", list(GRADERS))
def test_good_answer_makes_no_extra_call(session, name):
    g, w = GRADERS[name], _world(session)
    llm = _script(_goods(g))
    g.run(session, w, llm)
    assert len(llm.calls) == len(g.steps)
    assert all(len(c["messages"]) == 1 for c in llm.calls)
    rows = session.exec(select(Assessment)).all()
    assert len(rows) == g.rows and {a.score for a in rows} == {g.score}
    assert len(_events(session, "grade:check")) == len(g.steps)
    assert not _events(session, "grade:regenerated") and not _events(session, "grade:rejected")
    assert _row_tags(session) == [g.prompt.tag] * g.rows


@pytest.mark.parametrize("name,step", STEP_CASES)
def test_bad_then_good_regenerates_once_with_an_append_only_correction(session, name, step):
    g, w = GRADERS[name], _world(session)
    good, bad, rule_id = g.steps[step]
    goods = _goods(g)
    llm = _script(goods[:step] + [bad, good] + goods[step + 1:])
    g.run(session, w, llm)

    assert len(llm.calls) == len(g.steps) + 1
    first, retry = llm.calls[step], llm.calls[step + 1]
    assert len(first["messages"]) == 1  # history as sent is never edited afterwards
    assert retry["system"] == first["system"]
    assert retry["messages"][0] == first["messages"][0]
    assert retry["messages"][1] == {"role": "assistant", "content": bad}
    correction = retry["messages"][2]
    assert correction["role"] == "user" and f"- {rule_id}:" in correction["content"]
    assert len(retry["messages"]) == 3

    rows = session.exec(select(Assessment)).all()
    assert len(rows) == g.rows and {a.score for a in rows} == {g.score}
    regenerated = _events(session, "grade:regenerated")
    assert len(regenerated) == 1 and rule_id in regenerated[0].detail
    assert GRADE_CORRECTION.tag in [e.detail for e in _events(session, "prompt")]
    checks = [e.detail for e in _events(session, "grade:check")]
    assert len(checks) == len(g.steps) + 1
    assert f"attempt=1 fail FAIL {rule_id}" in checks[step]
    assert "attempt=2 pass" in checks[step + 1]
    assert not _events(session, "grade:rejected")

    # The row says the correction ran — built from the two tags — only for the grade that
    # was regenerated (a regenerated debrief writes no row).
    combined = f"{g.prompt.tag}+{GRADE_CORRECTION.tag}"
    assert combined == "+".join([g.prompt.tag, "grade.correction@v1"])
    if len(g.steps) == 1:
        expected = [combined] * g.rows
    else:
        expected = [combined if i == step else g.prompt.tag for i in range(g.rows)]
    assert _row_tags(session) == expected


@pytest.mark.parametrize("name,step", STEP_CASES)
def test_bad_twice_fails_closed(session, name, step):
    g, w = GRADERS[name], _world(session)
    _good, bad, rule_id = g.steps[step]
    # Prior evidence from an earlier grade of this roleplay / probe must survive a rejection.
    session.add(Assessment(concept_id=w.c1.id, kind="roleplay", prompt="p", score=0.9,
                           roleplay_session_id=w.rp.id))
    session.add(Assessment(concept_id=w.c1.id, kind="paper_probe", prompt="p", score=0.9,
                           paper_probe_id=w.pp.id))
    session.commit()
    if name == "decay":  # the recall prompt is armed before the grade; it must not move
        schedule_decay_check(session, w.c1.id)
    before = _learning_state(session, w)

    run = g.run
    if name == "decay":
        prompt = session.exec(select(RecallPrompt)).one()

        def run(s, w, llm):
            grade_decay_check(s, prompt.id, "from memory", llm=llm)

    llm = _script(_goods(g)[:step] + [bad, bad])
    with pytest.raises(GradeCheckError) as err:
        run(session, w, llm)

    assert err.value.rule_ids == (rule_id,)
    assert classify_llm_error(err.value) == "invalid_output"
    assert len(llm.calls) == step + 2  # one regeneration, then stop
    session.rollback()  # whatever the request would have discarded
    assert _learning_state(session, w) == before
    rejected = _events(session, "grade:rejected")  # committed: the trace survives the error
    assert len(rejected) == 1 and rule_id in rejected[0].detail


# ── Over HTTP: 502 invalid_output, nothing written ──────────────────────────

def _client(session, texts):
    app = create_app()
    llm = _script(texts)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)


def _post_assess(c, w):
    return c.post(f"/api/concepts/{w.c1.id}/assess",
                  json={"kind": "self_explanation", "response": "attention"})


def _post_teach(c, w):
    return c.post(f"/api/concepts/{w.c1.id}/teach", json={"explanation": "attention"})


def _post_consolidate(c, w):
    return c.post(f"/api/concepts/{w.c1.id}/productive_failure/consolidate",
                  json={"problem": "p", "attempt": "a"})


def _post_ship(c, w):
    return c.post(f"/api/deliverables/{w.deliverable.id}/ship", json={"content": "code"})


def _post_roleplay_end(c, w):
    return c.post(f"/api/roleplay/{w.rp.id}/end")


def _post_paper_submit(c, w):
    return c.post(f"/api/paper-probe/{w.pp.id}/submit")


ROUTES = {
    "assess": (_post_assess, [BAD_GRADE, BAD_GRADE]),
    "teach": (_post_teach, [BAD_TEACH, BAD_TEACH]),
    "consolidate": (_post_consolidate, [BAD_PF, BAD_PF]),
    "artifact": (_post_ship, [BAD_GRADE, BAD_GRADE]),
    "roleplay": (_post_roleplay_end, [GOOD_GRADE, BAD_GRADE, BAD_GRADE]),
    "paper_probe": (_post_paper_submit, [GOOD_GRADE, GOOD_GRADE, BAD_OUTCOME, BAD_OUTCOME]),
}


@pytest.mark.parametrize("name", list(ROUTES))
def test_route_returns_502_invalid_output_and_writes_nothing(session, name):
    post, texts = ROUTES[name]
    w = _world(session)
    before = _learning_state(session, w)
    r = post(_client(session, texts), w)
    assert r.status_code == 502, r.text
    assert r.json()["category"] == "invalid_output"
    assert "nothing was recorded" in r.json()["detail"]
    session.rollback()
    assert _learning_state(session, w) == before


def test_decay_route_returns_502_not_404(session):
    w = _world(session)
    prompt = schedule_decay_check(session, w.c1.id)
    before = _learning_state(session, w)
    r = _client(session, [BAD_GRADE, BAD_GRADE]).post(
        f"/api/decay/{prompt.id}/grade", json={"response": "from memory"})
    assert r.status_code == 502, r.text  # GradeCheckError is a ValueError: not "not found"
    assert r.json()["category"] == "invalid_output"
    session.rollback()
    assert _learning_state(session, w) == before


def test_rejection_trace_names_the_rules(session):
    w = _world(session)
    with pytest.raises(GradeCheckError):
        _run_assess(session, w, _script([BAD_GRADE, BAD_GRADE_MECH]))
    kinds = _kinds(session)
    assert kinds.count("grade:check") == 2
    assert kinds.index("grade:regenerated") < kinds.index("grade:rejected")
    checks = [e.detail for e in _events(session, "grade:check")]
    assert checks == ["grade attempt=1 fail FAIL G1", "grade attempt=2 fail FAIL G5"]
    assert "FAIL G5" in _events(session, "grade:rejected")[0].detail
    assert "assess:graded" not in kinds and "assess:estimate" not in kinds


def test_warning_is_recorded_but_does_not_block(session):
    w = _world(session)
    off_band = json.dumps({"score": 0.82, "mechanism_present": True, "verdict": "solid",
                           "gaps": [], **_NONE_NAMED})
    llm = _script([off_band])
    _run_assess(session, w, llm)
    assert len(llm.calls) == 1
    assert session.exec(select(Assessment)).one().score == 0.82
    assert _events(session, "grade:check")[0].detail == "grade attempt=1 pass WARN G8,G10"


# ── Stop reasons a retry can't fix: refusal / cut_off, one call, nothing written ──

_STOP_CATEGORY = {"refusal": "refusal", "max_tokens": "cut_off",
                  "model_context_window_exceeded": "cut_off"}
STOP_CASES = [(name, step, reason)
              for name, step in [(n, 0) for n in GRADERS] + [("roleplay", 2), ("paper_probe", 1)]
              for reason in _STOP_CATEGORY]


@pytest.mark.parametrize("name,step,reason", STOP_CASES)
def test_unretryable_stop_reason_raises_its_own_category_after_one_call(
        session, name, step, reason):
    g, w = GRADERS[name], _world(session)
    if name == "decay":
        schedule_decay_check(session, w.c1.id)
    before = _learning_state(session, w)
    run = g.run
    if name == "decay":
        prompt = session.exec(select(RecallPrompt)).one()

        def run(s, w, llm):
            grade_decay_check(s, prompt.id, "from memory", llm=llm)

    # Even a complete-looking answer is not trusted when the model stopped this way.
    stopped = LLMResponse(text=g.steps[step][0], stop_reason=reason)
    llm = _script(_goods(g)[:step] + [stopped])
    with pytest.raises(StructuredOutputError) as err:
        run(session, w, llm)

    assert not isinstance(err.value, GradeCheckError)
    assert err.value.reason == reason
    assert classify_llm_error(err.value) == _STOP_CATEGORY[reason]
    assert len(llm.calls) == step + 1  # no regeneration: it would stop the same way
    session.rollback()
    assert _learning_state(session, w) == before
    rejected = _events(session, "grade:rejected")
    assert len(rejected) == 1 and f"stop_reason={reason}" in rejected[0].detail
    assert not _events(session, "grade:regenerated")


def test_stop_reason_on_the_regeneration_also_stops(session):
    w = _world(session)
    llm = _script([BAD_GRADE, LLMResponse(text="", stop_reason="refusal")])
    with pytest.raises(StructuredOutputError) as err:
        _run_assess(session, w, llm)
    assert classify_llm_error(err.value) == "refusal" and len(llm.calls) == 2
    session.rollback()
    assert not session.exec(select(Assessment)).all()


def test_other_stop_reasons_are_checked_normally(session):
    w = _world(session)
    llm = _script([LLMResponse(text=GOOD_GRADE, stop_reason="end_turn")])
    _run_assess(session, w, llm)
    assert session.exec(select(Assessment)).one().prompt_tag == grade_prompt().tag


def test_route_reports_refusal_not_invalid_output(session):
    w = _world(session)
    before = _learning_state(session, w)
    r = _post_teach(_client(session, [LLMResponse(text="", stop_reason="refusal")]), w)
    assert r.status_code == 502 and r.json()["category"] == "refusal"
    session.rollback()
    assert _learning_state(session, w) == before


def test_huge_integer_score_is_a_g1_fail_not_a_crash():
    _data, report = check_output(
        GRADE_RUBRIC, '{"score": 1' + "0" * 400 + ', "verdict": "v", "gaps": ["x"], '
        '"missing_required": [], "misconceptions_committed": []}')
    assert report.failed_ids == ("G1",)
