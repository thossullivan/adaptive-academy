import json

from sqlmodel import select

from adaptive_academy.engine.paper_probe import direct, grade_paper_probe
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, KnowledgeEstimate, Milestone, PaperProbe, PaperProbeAnswer,
    Program, ProgramTopicLink, Rubric, Topic, Track,
)
from adaptive_academy.prompts import grade_prompt, PAPER_PROBE_OUTCOME


def _materialized(s):
    p = Program(title="PhD", goal_statement="g")
    s.add(p)
    s.commit()
    s.refresh(p)
    m = Milestone(program_id=p.id, title="Transformers", success_criteria="dissect the paper")
    s.add(m)
    s.commit()
    s.refresh(m)
    t = Topic(title="Transformers")
    s.add(t)
    s.commit()
    s.refresh(t)
    tr = Track(topic_id=t.id, title="tr")
    s.add(tr)
    s.commit()
    s.refresh(tr)
    c = Concept(track_id=tr.id, name="Self-attention", is_load_bearing=True)
    s.add(c)
    s.commit()
    s.refresh(c)
    s.add(KnowledgeEstimate(concept_id=c.id, level="low"))
    s.add(Rubric(concept_id=c.id, criteria=["explains QKV"], must_include=["query"], weak_signs=[]))
    s.add(ProgramTopicLink(milestone_id=m.id, topic_id=t.id, status="started"))
    s.commit()
    return p, m, c


def test_direct_generates_questions_and_activates(session):
    p, m, c = _materialized(session)
    pp = PaperProbe(program_id=p.id, milestone_id=m.id, paper_title="AIAYN",
                    paper_text="We propose the Transformer.", source="arxiv", status="drafting")
    session.add(pp)
    session.commit()
    session.refresh(pp)
    director_json = json.dumps({"questions": [
        {"axis": "method", "prompt": "How does self-attention compute weights?",
         "concept_ids": [c.id]},
        {"axis": "extension", "prompt": "What would you change?", "concept_ids": [c.id, 999]},
    ]})
    llm = ScriptedLLMClient([LLMResponse(text=director_json)])
    out = direct(session, pp, llm=llm)
    assert out.status == "answering"
    assert len(out.questions) == 2
    assert out.questions[0]["index"] == 0 and out.questions[0]["axis"] == "method"
    # unknown concept id 999 is filtered out; valid one kept
    assert out.questions[1]["concept_ids"] == [c.id]
    # the paper text and the concept must appear in the director's prompt
    assert "We propose the Transformer." in llm.calls[0]["messages"][0]["content"]
    assert "Self-attention" in llm.calls[0]["messages"][0]["content"]


def _answering_probe(s, p, m, c):
    pp = PaperProbe(program_id=p.id, milestone_id=m.id, paper_title="AIAYN",
                    paper_text="We propose the Transformer.", source="arxiv", status="answering",
                    questions=[{"index": 0, "axis": "method", "prompt": "How does attention work?",
                                "concept_ids": [c.id]}])
    s.add(pp)
    s.commit()
    s.refresh(pp)
    s.add(PaperProbeAnswer(probe_id=pp.id, question_index=0,
                           content="It computes a query, key, value..."))
    s.commit()
    return pp


def test_grade_writes_one_assessment_per_concept_and_outcome(session):
    p, m, c = _materialized(session)
    pp = _answering_probe(session, p, m, c)
    grade_json = json.dumps({"score": 0.82, "verdict": "solid", "mechanism_present": True,
                             "gaps": [], "missing_required": [], "misconceptions_committed": []})
    outcome_json = json.dumps({"result": "sharp critique", "summary": "Good QKV account."})
    llm = ScriptedLLMClient([LLMResponse(text=grade_json), LLMResponse(text=outcome_json)])
    out = grade_paper_probe(session, pp, llm=llm)
    assert len(out) == 1
    a = out[0]
    assert a.kind == "paper_probe" and a.paper_probe_id == pp.id and a.concept_id == c.id
    # Graded per concept by assess_concept's GRADE; PAPER_PROBE_OUTCOME only wrote the outcome.
    assert a.prompt_tag == grade_prompt().tag != PAPER_PROBE_OUTCOME.tag
    session.refresh(pp)
    assert pp.status == "graded" and pp.outcome["result"] == "sharp critique"


def test_regrade_is_idempotent(session):
    p, m, c = _materialized(session)
    pp = _answering_probe(session, p, m, c)
    grade_json = json.dumps({"score": 0.82, "verdict": "solid", "mechanism_present": True,
                             "gaps": [], "missing_required": [], "misconceptions_committed": []})
    outcome_json = json.dumps({"result": "sharp critique", "summary": "s"})
    llm = ScriptedLLMClient([LLMResponse(text=grade_json), LLMResponse(text=outcome_json),
                             LLMResponse(text=grade_json), LLMResponse(text=outcome_json)])
    grade_paper_probe(session, pp, llm=llm)
    grade_paper_probe(session, pp, llm=llm)
    rows = session.exec(select(Assessment).where(Assessment.paper_probe_id == pp.id)).all()
    assert len(rows) == 1  # second grade replaced, not duplicated


def test_concept_not_exercised_gets_no_evidence(session):
    p, m, c = _materialized(session)
    pp = PaperProbe(program_id=p.id, milestone_id=m.id, paper_title="AIAYN",
                    paper_text="x", source="arxiv", status="answering",
                    questions=[{"index": 0, "axis": "method", "prompt": "q", "concept_ids": []}])
    session.add(pp)
    session.commit()
    session.refresh(pp)
    session.add(PaperProbeAnswer(probe_id=pp.id, question_index=0, content="a"))
    session.commit()
    outcome_json = json.dumps({"result": "n/a", "summary": "s"})
    llm = ScriptedLLMClient([LLMResponse(text=outcome_json)])  # no grade call expected
    out = grade_paper_probe(session, pp, llm=llm)
    assert out == []
    session.refresh(pp)
    assert pp.status == "graded"
