import json

from adaptive_academy.engine.gates import evaluate_concept, evaluate_milestone_readonly
from adaptive_academy.engine.paper_probe import grade_paper_probe
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, KnowledgeEstimate, Milestone, PaperProbe, PaperProbeAnswer,
    Program, ProgramTopicLink, Rubric, Topic, Track,
)


def test_paper_probe_at_threshold_counts_as_artifact_ok():
    rows = [Assessment(id=1, concept_id=1, kind="paper_probe", prompt="p", score=0.8)]
    ev = evaluate_concept(1, "Self-attention", rows)
    assert ev.artifact_ok is True


def test_paper_probe_below_threshold_does_not_count():
    rows = [Assessment(id=1, concept_id=1, kind="paper_probe", prompt="p", score=0.5)]
    ev = evaluate_concept(1, "Self-attention", rows)
    assert ev.artifact_ok is False


def _seed(s):
    p = Program(title="PhD", goal_statement="g")
    s.add(p)
    s.commit()
    s.refresh(p)
    m = Milestone(program_id=p.id, title="Transformers", success_criteria="dissect")
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
    s.add(Rubric(concept_id=c.id, criteria=["QKV"], must_include=[], weak_signs=[]))
    s.add(ProgramTopicLink(milestone_id=m.id, topic_id=t.id, status="started"))
    pp = PaperProbe(program_id=p.id, milestone_id=m.id, paper_title="AIAYN", paper_text="x",
                    source="arxiv", status="answering",
                    questions=[{"index": 0, "axis": "method", "prompt": "q", "concept_ids": [c.id]}])
    s.add(pp)
    s.commit()
    s.refresh(pp)
    s.add(PaperProbeAnswer(probe_id=pp.id, question_index=0, content="QKV explanation"))
    s.commit()
    return m, c, pp


def test_graded_probe_reaches_milestone_gate_artifact_axis(session):
    m, c, pp = _seed(session)
    grade_json = json.dumps({"score": 0.8, "verdict": "solid", "mechanism_present": True,
                             "gaps": []})
    outcome_json = json.dumps({"result": "sharp", "summary": "s"})
    llm = ScriptedLLMClient([LLMResponse(text=grade_json), LLMResponse(text=outcome_json)])
    grade_paper_probe(session, pp, llm=llm)
    report = evaluate_milestone_readonly(session, m)
    evidence = next(e for e in report.concepts if e.concept_id == c.id)
    assert evidence.artifact_ok is True
