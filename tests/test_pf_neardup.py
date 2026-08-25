import json

from sqlmodel import select

from adaptive_academy.engine.memory import content_hash, index_question
from adaptive_academy.engine.productive_failure import generate_challenge
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import AgentEvent, Chunk, Concept, Topic, Track


def test_productive_failure_rejects_one_near_duplicate_and_persists_retry(session):
    topic = Topic(title="Caching")
    session.add(topic)
    session.flush()
    track = Track(topic_id=topic.id, title="Systems")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="cache eviction")
    session.add(concept)
    session.flush()
    prior = "Design a cache eviction policy for a bursty cache eviction workload."
    index_question(
        session,
        text=prior,
        source_ref="assessment:1#q",
        topic_id=topic.id,
        concept_id=concept.id,
    )
    session.commit()

    fresh = "Compare two indexing strategies under skewed read traffic."
    llm = ScriptedLLMClient(
        [
            LLMResponse(text=json.dumps({"problem": prior})),
            LLMResponse(text=json.dumps({"problem": fresh})),
        ]
    )

    result = generate_challenge(
        session,
        concept,
        llm=llm,
        retriever=ScriptedRetriever(),
    )

    assert result == fresh
    assert len(llm.calls) == 2
    assert "<<<ALREADY_COVERED>>>" in llm.calls[0]["messages"][0]["content"]
    assert prior in llm.calls[1]["messages"][0]["content"]
    assert session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:neardup_reject")
    ).one()
    persisted = session.exec(
        select(Chunk).where(
            Chunk.source_ref
            == f"productive_failure:{concept.id}:{content_hash(fresh)}"
        )
    ).one()
    assert persisted.text == fresh
