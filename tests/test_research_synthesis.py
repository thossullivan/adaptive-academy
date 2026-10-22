import json

import pytest

from adaptive_academy.engine.research import Foundation, synthesize_foundation
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse


def _payload() -> str:
    return json.dumps(
        {
            "overview": "Transformers use attention.",
            "key_concepts": ["self-attention", "softmax"],
            "prerequisite_map": {"self-attention": ["dot product"]},
        }
    )


def test_synthesize_parses_plain_json():
    llm = ScriptedLLMClient([LLMResponse(text=_payload())])
    f = synthesize_foundation("LLMs", "learn", [RawSource(title="A", url="a", tier=1)], llm)
    assert isinstance(f, Foundation)
    assert f.overview == "Transformers use attention."
    assert f.key_concepts == ["self-attention", "softmax"]
    assert f.prerequisite_map == {"self-attention": ["dot product"]}


def test_synthesize_strips_markdown_fences():
    llm = ScriptedLLMClient([LLMResponse(text="```json\n" + _payload() + "\n```")])
    f = synthesize_foundation("LLMs", "learn", [], llm)
    assert f.key_concepts == ["self-attention", "softmax"]


def test_synthesize_includes_sources_in_prompt():
    llm = ScriptedLLMClient([LLMResponse(text=_payload())])
    synthesize_foundation("LLMs", "learn", [RawSource(title="Attention Paper", url="u", tier=1)], llm)
    sent = llm.calls[0]["messages"][0]["content"]
    assert "Attention Paper" in sent


# ── Concept-name checks (engine/concept_names.py) ───────────────────────────
# A name that states a formula or result puts the answer on screen before the learner
# tries (Tutor page, probe text). Check, regenerate once with an append-only correction
# naming the rule ids, then repair deterministically and record a WARN event.

_LEAKY = "Gradient of the cost: ∇J(θ)=Xᵀ(Xθ−y) (divided by m if using the averaged cost)"


def _leaky_payload() -> str:
    return json.dumps({
        "overview": "Gradient descent on least squares.",
        "key_concepts": [_LEAKY, "Batch gradient descent update"],
        "prerequisite_map": {"Batch gradient descent update": [_LEAKY]},
    })


def _clean_payload() -> str:
    return json.dumps({
        "overview": "Gradient descent on least squares.",
        "key_concepts": ["Gradient of the cost", "Batch gradient descent update"],
        "prerequisite_map": {"Batch gradient descent update": ["Gradient of the cost"]},
    })


def _recorder():
    events: list[tuple[str, str]] = []
    return events, lambda kind, detail="": events.append((kind, detail))


def test_clean_names_take_one_call():
    llm = ScriptedLLMClient([LLMResponse(text=_payload())])
    events, emit = _recorder()
    synthesize_foundation("LLMs", "learn", [], llm, emit=emit)
    assert len(llm.calls) == 1
    assert [k for k, _ in events] == ["concepts:check"]
    assert "pass" in events[0][1]


def test_leaky_names_regenerate_once_with_append_only_correction():
    from adaptive_academy.prompts import CONCEPT_NAME_CORRECTION

    llm = ScriptedLLMClient([LLMResponse(text=_leaky_payload()),
                             LLMResponse(text=_clean_payload())])
    events, emit = _recorder()
    f = synthesize_foundation("LLMs", "learn", [], llm, emit=emit)
    assert f.key_concepts == ["Gradient of the cost", "Batch gradient descent update"]
    assert len(llm.calls) == 2
    first, second = llm.calls[0]["messages"], llm.calls[1]["messages"]
    assert second[: len(first)] == first  # append-only: the original turn is untouched
    assert second[-2] == {"role": "assistant", "content": _leaky_payload()}
    correction = second[-1]["content"]
    assert second[-1]["role"] == "user"
    assert "N3" in correction and "N4" in correction and "Gradient of the cost" in correction
    kinds = [k for k, _ in events]
    assert kinds == ["concepts:check", "concepts:regenerated", "prompt", "concepts:check"]
    assert events[2][1] == CONCEPT_NAME_CORRECTION.tag


def test_names_still_leaky_after_regeneration_are_repaired_not_fatal():
    llm = ScriptedLLMClient([LLMResponse(text=_leaky_payload()),
                             LLMResponse(text=_leaky_payload())])
    events, emit = _recorder()
    f = synthesize_foundation("LLMs", "learn", [], llm, emit=emit)
    assert len(llm.calls) == 2  # never a third call
    assert f.key_concepts == ["Gradient of the cost", "Batch gradient descent update"]
    assert f.prerequisite_map == {"Batch gradient descent update": ["Gradient of the cost"]}
    repaired = [d for k, d in events if k == "concepts:repaired"]
    assert len(repaired) == 1 and repaired[0].startswith("WARN ")
    assert "Gradient of the cost" in repaired[0]


def test_unparseable_regeneration_falls_back_to_repairing_the_first_answer():
    llm = ScriptedLLMClient([LLMResponse(text=_leaky_payload()),
                             LLMResponse(text="sorry, no JSON here")])
    events, emit = _recorder()
    f = synthesize_foundation("LLMs", "learn", [], llm, emit=emit)
    assert f.key_concepts == ["Gradient of the cost", "Batch gradient descent update"]
    assert any(k == "concepts:repaired" for k, _ in events)


class _RetryRaises(ScriptedLLMClient):
    """First call answers; the correction retry fails (budget, rate limit, network)."""

    def complete(self, system, messages, tools):
        if self.calls:
            self.calls.append({"system": system, "messages": messages, "tools": tools})
            raise RuntimeError("daily budget reached")
        return super().complete(system, messages, tools)


def test_retry_exception_repairs_the_first_answer():
    llm = _RetryRaises([LLMResponse(text=_leaky_payload())])
    events, emit = _recorder()
    f = synthesize_foundation("LLMs", "learn", [], llm, emit=emit)
    assert len(llm.calls) == 2
    assert f.key_concepts == ["Gradient of the cost", "Batch gradient descent update"]
    kinds = [k for k, _ in events]
    assert "concepts:retry_failed" in kinds and "concepts:repaired" in kinds
    assert "RuntimeError" in dict(events)["concepts:retry_failed"]


def _payload_with(key_concepts) -> str:
    return json.dumps({"overview": "o", "key_concepts": key_concepts, "prerequisite_map": {}})


def test_retry_with_fewer_key_concepts_is_ignored():
    # The clean retry dropped a concept: keep (and repair) the fuller first answer.
    llm = ScriptedLLMClient([LLMResponse(text=_leaky_payload()),
                             LLMResponse(text=_payload_with(["Gradient of the cost"]))])
    events, emit = _recorder()
    f = synthesize_foundation("LLMs", "learn", [], llm, emit=emit)
    assert f.key_concepts == ["Gradient of the cost", "Batch gradient descent update"]
    assert any(k == "concepts:retry_failed" for k, _ in events)


def test_retry_with_no_key_concepts_is_ignored():
    llm = ScriptedLLMClient([LLMResponse(text=_leaky_payload()),
                             LLMResponse(text=_payload_with([]))])
    f = synthesize_foundation("LLMs", "learn", [], llm)
    assert f.key_concepts == ["Gradient of the cost", "Batch gradient descent update"]


def test_retry_failure_keeps_paid_for_sources(session):
    from sqlmodel import select

    from adaptive_academy.engine.research import research_topic
    from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
    from adaptive_academy.models import SourceDoc, Topic, TopicFoundation, TopicIntent

    topic = Topic(title="GD")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="g", prior_knowledge="p", time_budget="t")
    session.add(intent)
    session.commit()
    researcher = ScriptedResearcherClient(
        {"foundational_papers": [RawSource(title="A", url="https://example.org/a", tier=1)]})
    research_topic(session, topic, intent, researcher=researcher,
                   llm=_RetryRaises([LLMResponse(text=_leaky_payload())]), max_subagents=1)
    assert len(session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic.id)).all()) == 1
    fnd = session.exec(select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)).one()
    assert fnd.key_concepts == ["Gradient of the cost", "Batch gradient descent update"]


def test_research_topic_persists_repaired_names_and_traces_them(session):
    from sqlmodel import select

    from adaptive_academy.engine.research import research_topic
    from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
    from adaptive_academy.models import AgentEvent, Topic, TopicFoundation, TopicIntent

    topic = Topic(title="Gradient descent for linear regression")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="g", prior_knowledge="p", time_budget="t")
    session.add(intent)
    session.commit()
    llm = ScriptedLLMClient([LLMResponse(text=_leaky_payload()),
                             LLMResponse(text=_leaky_payload())])
    research_topic(session, topic, intent, researcher=ScriptedResearcherClient({}), llm=llm,
                   max_subagents=1)
    fnd = session.exec(select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)).one()
    assert fnd.key_concepts == ["Gradient of the cost", "Batch gradient descent update"]
    kinds = [e.kind for e in session.exec(
        select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()]
    assert "concepts:regenerated" in kinds and "concepts:repaired" in kinds


def test_concepts_wrapped_in_objects_keep_their_names():
    # Final-review regression: object entries used to be dropped, leaving a topic with
    # no concepts and no event.
    from adaptive_academy.engine.research import _parse_foundation_json

    f = _parse_foundation_json(json.dumps({
        "overview": "o",
        "key_concepts": [{"name": "Chain rule"}, {"concept": "Gradient"}, "Loss"],
        "prerequisite_map": {"Gradient": [{"name": "Chain rule"}]},
    }))
    assert f.key_concepts == ["Chain rule", "Gradient", "Loss"]
    assert f.prerequisite_map == {"Gradient": ["Chain rule"]}


def test_concepts_with_no_usable_name_fail_legibly():
    from adaptive_academy.engine.research import _parse_foundation_json
    from adaptive_academy.llm.types import StructuredOutputError

    with pytest.raises(StructuredOutputError):
        _parse_foundation_json(json.dumps({"overview": "o", "key_concepts": [{"x": 1}, 2]}))
