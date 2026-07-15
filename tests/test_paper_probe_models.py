from sqlmodel import select

from adaptive_academy.models import (
    AgentEvent, Assessment, Concept, KnowledgeEstimate, Milestone, PaperProbe,
    PaperProbeAnswer, Program, Track, Topic,
)


def _concept(s):
    t = Topic(title="T")
    s.add(t)
    s.commit()
    s.refresh(t)
    tr = Track(topic_id=t.id, title="tr")
    s.add(tr)
    s.commit()
    s.refresh(tr)
    c = Concept(track_id=tr.id, name="Attention", is_load_bearing=True)
    s.add(c)
    s.commit()
    s.refresh(c)
    s.add(KnowledgeEstimate(concept_id=c.id, level="low"))
    s.commit()
    return c


def test_paper_probe_roundtrip(session):
    p = Program(title="PhD", goal_statement="g")
    session.add(p)
    session.commit()
    session.refresh(p)
    m = Milestone(program_id=p.id, title="Transformers", success_criteria="read the paper")
    session.add(m)
    session.commit()
    session.refresh(m)
    pp = PaperProbe(program_id=p.id, milestone_id=m.id, paper_title="Attention Is All You Need",
                    paper_url="https://arxiv.org/abs/1706.03762", paper_text="We propose...",
                    source="arxiv", status="answering",
                    questions=[{"index": 0, "axis": "method", "prompt": "How does self-attention work?",
                                "concept_ids": [1]}])
    session.add(pp)
    session.commit()
    session.refresh(pp)
    assert pp.id is not None and pp.questions[0]["axis"] == "method"

    session.add(PaperProbeAnswer(probe_id=pp.id, question_index=0, content="It computes..."))
    session.commit()
    rows = session.exec(select(PaperProbeAnswer).where(PaperProbeAnswer.probe_id == pp.id)).all()
    assert rows[0].content == "It computes..."


def test_assessment_and_event_carry_paper_probe_id(session):
    c = _concept(session)
    p = Program(title="PhD", goal_statement="g")
    session.add(p)
    session.commit()
    session.refresh(p)
    m = Milestone(program_id=p.id, title="M", success_criteria="c")
    session.add(m)
    session.commit()
    session.refresh(m)
    pp = PaperProbe(program_id=p.id, milestone_id=m.id)
    session.add(pp)
    session.commit()
    session.refresh(pp)
    a = Assessment(concept_id=c.id, kind="paper_probe", prompt="p", score=0.8, paper_probe_id=pp.id)
    session.add(a)
    e = AgentEvent(program_id=p.id, kind="paper_probe:graded", paper_probe_id=pp.id)
    session.add(e)
    session.commit()
    session.refresh(a)
    session.refresh(e)
    assert a.paper_probe_id == pp.id and e.paper_probe_id == pp.id
