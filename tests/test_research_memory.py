import json

from sqlmodel import select

from adaptive_academy.engine.memory import index_text
from adaptive_academy.engine.research import research_topic
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import AgentEvent, Topic, TopicIntent


def test_research_lists_existing_vault_headings_in_already_covered_block(session):
    topic = Topic(title="Graph Memory")
    session.add(topic)
    session.flush()
    intent = TopicIntent(topic_id=topic.id, goal="build graph memory systems")
    session.add(intent)
    index_text(
        session,
        kind="vault_note",
        text="Graph memory systems connect retrieved facts.",
        source_ref="vault:graph-memory",
        doc_title="Existing Notes",
        topic_id=topic.id,
        heading="Retrieval architecture",
    )
    session.commit()
    payload = json.dumps(
        {
            "overview": "Overview",
            "key_concepts": ["retrieval"],
            "prerequisite_map": {},
        }
    )
    llm = ScriptedLLMClient([LLMResponse(text=payload)])

    research_topic(
        session,
        topic,
        intent,
        researcher=ScriptedResearcherClient({}),
        llm=llm,
        retriever=ScriptedRetriever(),
        max_subagents=1,
    )

    user = llm.calls[0]["messages"][0]["content"]
    assert "<<<ALREADY_COVERED>>>" in user
    assert "- Retrieval architecture" in user
    assert "Graph memory systems connect retrieved facts." not in user
    assert session.exec(
        select(AgentEvent).where(
            AgentEvent.topic_id == topic.id,
            AgentEvent.kind == "memory:retrieve",
        )
    ).all()
