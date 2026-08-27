import json

from sqlmodel import select

from adaptive_academy.engine.memory import index_question, index_text
from adaptive_academy.engine.roleplay import direct
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Concept,
    Milestone,
    Program,
    ProgramTopicLink,
    RoleplaySession,
    Topic,
    Track,
)


def test_roleplay_director_injects_memory_and_rejects_duplicate_opening(session):
    program = Program(title="Sales")
    session.add(program)
    session.flush()
    milestone = Milestone(
        program_id=program.id,
        title="Discovery",
        success_criteria="run a discovery call",
    )
    topic = Topic(title="Discovery")
    session.add_all([milestone, topic])
    session.flush()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.flush()
    concept = Concept(
        track_id=track.id,
        name="discovery questions",
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
    prior = "A discovery questions buyer challenges your evidence in a discovery call."
    index_question(
        session,
        text=prior,
        source_ref="roleplaysession:old#opening",
        topic_id=topic.id,
        concept_id=concept.id,
    )
    index_text(
        session,
        kind="vault_note",
        text="Discovery questions need concrete evidence from the buyer.",
        source_ref="vault:discovery",
        topic_id=topic.id,
        heading="Discovery evidence",
    )
    rp = RoleplaySession(
        program_id=program.id,
        milestone_id=milestone.id,
        status="briefing",
    )
    session.add(rp)
    session.commit()
    session.refresh(rp)

    first = {
        "persona": "Buyer",
        "goal": "resist",
        "situation": prior,
        "hidden_objections": [],
        "win_conditions": [],
        "difficulty": "medium",
    }
    second = {
        **first,
        "situation": "A procurement lead asks for a measurable implementation plan.",
    }
    llm = ScriptedLLMClient(
        [
            LLMResponse(text=json.dumps(first)),
            LLMResponse(text=json.dumps(second)),
        ]
    )

    result = direct(session, rp, llm=llm, retriever=ScriptedRetriever())

    first_user = llm.calls[0]["messages"][0]["content"]
    assert "<<<MEMORY>>>" in first_user
    assert "<<<ALREADY_COVERED>>>" in first_user
    assert prior in first_user
    assert len(llm.calls) == 2
    assert prior in llm.calls[1]["messages"][0]["content"]
    assert result.persona_brief["situation"] == second["situation"]
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:neardup_reject")
    ).one()
    assert event.roleplay_session_id == rp.id
