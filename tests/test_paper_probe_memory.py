import json

from sqlmodel import select

from adaptive_academy.engine.memory import index_question
from adaptive_academy.engine.paper_probe import direct
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Chunk,
    Concept,
    Milestone,
    PaperProbe,
    Program,
    ProgramTopicLink,
    Topic,
    Track,
)


def test_paper_probe_rejects_when_any_generated_question_is_a_near_duplicate(session):
    program = Program(title="Papers")
    session.add(program)
    session.flush()
    milestone = Milestone(
        program_id=program.id,
        title="Attention",
        success_criteria="critique attention papers",
    )
    topic = Topic(title="Attention")
    session.add_all([milestone, topic])
    session.flush()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.flush()
    concept = Concept(
        track_id=track.id,
        name="attention validity",
        is_load_bearing=True,
    )
    session.add(concept)
    session.flush()
    session.add(
        ProgramTopicLink(
            milestone_id=milestone.id,
            topic_id=topic.id,
            status="started",
        )
    )
    prior = "Which attention validity assumption fails under distribution shift?"
    index_question(
        session,
        text=prior,
        source_ref="paperprobe:old#q:0",
        topic_id=topic.id,
        concept_id=concept.id,
    )
    probe = PaperProbe(
        program_id=program.id,
        milestone_id=milestone.id,
        paper_title="Attention Study",
        paper_text="We test attention under controlled conditions.",
        status="drafting",
    )
    session.add(probe)
    session.commit()
    session.refresh(probe)

    first_questions = [
        {
            "axis": "method",
            "prompt": "How are attention weights measured?",
            "concept_ids": [concept.id],
        },
        {
            "axis": "validity",
            "prompt": prior,
            "concept_ids": [concept.id],
        },
    ]
    fresh = "How would hidden confounding change the reported conclusion?"
    second_questions = [
        {
            "axis": "extension",
            "prompt": fresh,
            "concept_ids": [concept.id],
        }
    ]
    llm = ScriptedLLMClient(
        [
            LLMResponse(text=json.dumps({"questions": first_questions})),
            LLMResponse(text=json.dumps({"questions": second_questions})),
        ]
    )

    result = direct(session, probe, llm=llm, retriever=ScriptedRetriever())

    assert "<<<ALREADY_COVERED>>>" in llm.calls[0]["messages"][0]["content"]
    assert prior in llm.calls[0]["messages"][0]["content"]
    assert len(llm.calls) == 2
    assert prior in llm.calls[1]["messages"][0]["content"]
    assert [question["prompt"] for question in result.questions] == [fresh]
    indexed = session.exec(
        select(Chunk).where(Chunk.source_ref == f"paperprobe:{probe.id}#q:0")
    ).one()
    assert indexed.text == fresh
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:neardup_reject")
    ).one()
    assert event.paper_probe_id == probe.id
