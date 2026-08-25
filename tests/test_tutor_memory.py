import adaptive_academy.engine.tutor_sdk as tutor_sdk
from sqlmodel import select

from adaptive_academy.engine.memory import index_message
from adaptive_academy.engine.tutor import run_tutor_turn
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Concept,
    Conversation,
    Message,
    Topic,
    Track,
)


def _seed_memory(session) -> tuple[Conversation, str, str]:
    topic = Topic(title="Attention")
    session.add(topic)
    session.flush()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="self-attention")
    session.add(concept)
    session.flush()

    prior = Conversation(topic_id=topic.id, concept_id=concept.id)
    current = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add_all([prior, current])
    session.flush()

    prior_text = (
        "PRIOR TUTOR MEMORY: self-attention uses retrieval context. " * 5
    ).strip()
    prior_message = Message(
        conversation_id=prior.id,
        role="tutor",
        content=prior_text,
    )
    current_text = "CURRENT CONVERSATION PRIVATE MARKER about self-attention"
    current_message = Message(
        conversation_id=current.id,
        role="user",
        content=current_text,
    )
    session.add_all([prior_message, current_message])
    session.flush()
    index_message(
        session,
        prior_message,
        concept_id=concept.id,
        topic_id=topic.id,
    )
    index_message(
        session,
        current_message,
        concept_id=concept.id,
        topic_id=topic.id,
    )
    session.commit()
    session.refresh(current)
    return current, prior_text, current_text


def test_tutor_injects_prior_memory_and_excludes_current_conversation(session):
    convo, prior_text, current_text = _seed_memory(session)
    llm = ScriptedLLMClient([LLMResponse(text="Try comparing the query and key.")])

    result = run_tutor_turn(
        session,
        convo,
        "How does self-attention use retrieval context?",
        llm,
        retriever=ScriptedRetriever(),
    )

    system = llm.calls[0]["system"]
    assert "<<<ALREADY_COVERED>>>" in system
    assert prior_text in system
    assert current_text not in system
    assert result.memory
    events = session.exec(
        select(AgentEvent).where(
            AgentEvent.conversation_id == convo.id,
            AgentEvent.kind == "memory:retrieve",
        )
    ).all()
    assert events


class _FakeResult:
    def __init__(self, result: str):
        self.result = result
        self.is_error = False


def test_tutor_sdk_injects_prior_memory_and_excludes_current_conversation(
    session,
    monkeypatch,
):
    convo, prior_text, current_text = _seed_memory(session)

    async def fake_query(prompt, options):
        assert "Learner: Explain self-attention retrieval context." in prompt
        assert "<<<ALREADY_COVERED>>>" in options.system_prompt
        assert prior_text in options.system_prompt
        assert current_text not in options.system_prompt
        yield _FakeResult("Consider what the query selects.")

    monkeypatch.setattr(tutor_sdk, "ResultMessage", _FakeResult)
    monkeypatch.setattr(tutor_sdk, "query", fake_query)

    result = tutor_sdk.run_tutor_turn_sdk(
        session,
        convo,
        "Explain self-attention retrieval context.",
        retriever=ScriptedRetriever(),
    )

    assert result.memory
    assert session.exec(
        select(AgentEvent).where(
            AgentEvent.conversation_id == convo.id,
            AgentEvent.kind == "memory:retrieve",
        )
    ).all()
