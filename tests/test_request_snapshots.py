"""Pin the exact request each real call surface sends to the Anthropic API.

Any change to a prompt, a schema, a tool, the model, a parameter, or where the prompt-cache
breakpoints sit changes tests/fixtures/request_snapshots.json, so it shows up as a reviewed
diff instead of slipping through. Per call it records: the usage operation, role and model,
max_tokens, a sha256 of the system text (and of the messages), each tool's name with a sha256
of its full definition, tool_choice, any other request parameters, and every cache_control
location.

The real call sites are driven end to end: the engine functions (tutor turn, assessment,
curriculum, research search and foundation) run against the real AnthropicLLMClient /
AnthropicResearcherClient from api/deps, whose SDK `messages.create` is replaced by a fake
that records the kwargs and returns canned responses. No network. The date in the system
prompt is frozen and the models are pinned to the defaults, so the hashes are stable.

After an intended change, regenerate the fixture and review its diff:

    UPDATE_REQUEST_SNAPSHOTS=1 uv run pytest tests/test_request_snapshots.py
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from adaptive_academy.api import deps
from adaptive_academy.llm import today
from adaptive_academy.models import (
    Concept, Conversation, KnowledgeEstimate, SourceDoc, Topic, TopicFoundation, TopicIntent,
    Track,
)

SNAPSHOT = Path(__file__).parent / "fixtures" / "request_snapshots.json"
FROZEN_NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
_SUMMARISED = {"model", "max_tokens", "system", "messages", "tools", "tool_choice",
               "cache_control"}


def _sha(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def _strip_cache_control(value):
    if isinstance(value, dict):
        return {k: _strip_cache_control(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [_strip_cache_control(v) for v in value]
    return value


def _cache_locations(kw) -> list[str]:
    where = ["top-level"] if "cache_control" in kw else []
    system = kw.get("system")
    if isinstance(system, list):
        where += [f"system[{i}]" for i, b in enumerate(system) if "cache_control" in b]
    where += [f"tools[{i}]" for i, t in enumerate(kw.get("tools") or []) if "cache_control" in t]
    for i, m in enumerate(kw.get("messages") or []):
        content = m.get("content")
        if isinstance(content, list):
            where += [f"messages[{i}].content[{j}]" for j, b in enumerate(content)
                      if isinstance(b, dict) and "cache_control" in b]
    return where


def _summarise(kw, usage_call) -> dict:
    system = kw.get("system")
    system_text = system if isinstance(system, str) else "".join(b["text"] for b in system)
    return {
        "operation": usage_call["operation"],
        "role": usage_call["role"],
        "model": kw["model"],
        "max_tokens": kw["max_tokens"],
        "system_sha256": _sha(system_text),
        "system_chars": len(system_text),
        "tools": [{"name": t.get("name"), "type": t.get("type", "custom"),
                   "sha256": _sha(_strip_cache_control(t))} for t in kw.get("tools") or []],
        "tool_choice": kw.get("tool_choice"),
        "message_roles": [m["role"] for m in kw["messages"]],
        "messages_sha256": _sha(_strip_cache_control(kw["messages"])),
        "other_params": {k: v for k, v in sorted(kw.items()) if k not in _SUMMARISED},
        "cache_control": _cache_locations(kw),
    }


# --- the fake SDK ---------------------------------------------------------------------


class _Recorder:
    def __init__(self):
        self.calls: list[dict] = []
        self.usage: list[dict] = []
        self.queue: list = []

    def summaries(self) -> list[dict]:
        assert len(self.calls) == len(self.usage), "every call records its usage once"
        return [_summarise(kw, u) for kw, u in zip(self.calls, self.usage)]


def _resp(*blocks, stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0,
                            cache_read_input_tokens=0, server_tool_use=None)
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage)


def _text(text):
    return _resp(TextBlock(type="text", text=text))


def _tool(name, payload, id_="toolu_01"):
    return _resp(ToolUseBlock(type="tool_use", id=id_, name=name, input=payload),
                 stop_reason="tool_use")


@pytest.fixture
def rec(monkeypatch):
    from adaptive_academy.settings import settings

    recorder = _Recorder()

    class _Messages:
        def create(self, **kw):
            recorder.calls.append(json.loads(json.dumps(kw)))  # a copy, as sent
            return recorder.queue.pop(0)

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    def _record_usage(**kw):
        recorder.usage.append({"operation": kw["operation"], "role": kw["role"]})

    for module in ("anthropic_client", "anthropic_researcher"):
        monkeypatch.setattr(f"adaptive_academy.llm.{module}.Anthropic", _FakeAnthropic)
        monkeypatch.setattr(f"adaptive_academy.llm.{module}.record_usage", _record_usage)
    monkeypatch.setattr(today, "local_now", lambda: FROZEN_NOW)
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    # Pin the defaults (llm/registry.py), whatever the developer's .env says.
    monkeypatch.setattr(settings, "reasoning_model", "")
    monkeypatch.setattr(settings, "copy_model", "")
    return recorder


# --- the call surfaces ----------------------------------------------------------------


def _concept(session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="How GPT-style models work.",
                                key_concepts=["self-attention", "linear algebra"],
                                prerequisite_map={"self-attention": ["linear algebra"]}))
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="self-attention")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="medium", confidence=0.5))
    session.commit()
    return topic, concept


def _tutor_turn(session, rec):
    from adaptive_academy.engine.tutor import run_tutor_turn

    topic, concept = _concept(session)
    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    rec.queue += [
        _tool("log_attempt", {"summary": "softmax over QK^T"}),
        _text("Good start. Why divide by sqrt(d_k)?"),
        _text("Right: it keeps the softmax out of saturation."),
    ]
    llm = deps.get_llm()
    # Two learner turns: the first runs a tool step, the second resends the history.
    run_tutor_turn(session, convo, "Attention is softmax(QK^T)V.", llm)
    run_tutor_turn(session, convo, "To keep the dot products from growing with d_k.", llm)


def _assessment_grade(session, rec):
    from adaptive_academy.engine.assess import assess_concept

    _, concept = _concept(session)
    rec.queue += [
        _text(json.dumps({"criteria": ["names QK^T"], "must_include": ["softmax"],
                          "strong_signs": [], "weak_signs": [], "source_refs": []})),
        _text(json.dumps({"score": 0.6, "verdict": "partial", "gaps": ["no scaling"],
                          "mechanism_present": True})),
    ]
    # Rubric generation, then the grade.
    assess_concept(session, concept, "self_explanation",
                   "Each token scores the others with QK^T and takes a softmax.",
                   llm=deps.get_llm())


def _curriculum(session, rec):
    from adaptive_academy.engine.curriculum import generate_curriculum

    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="build a GPT", prior_knowledge="strong",
                         time_budget="10h/wk")
    foundation = TopicFoundation(topic_id=topic.id, overview="ov",
                                 key_concepts=["self-attention", "linear algebra"],
                                 prerequisite_map={"self-attention": ["linear algebra"]})
    source = SourceDoc(topic_id=topic.id, title="Attention Is All You Need",
                       url="https://arxiv.org/abs/1706.03762", tier=1, summary="s",
                       status="accepted", rank=0)
    session.add_all([intent, foundation, source])
    session.commit()
    rec.queue.append(_tool("emit_track", {
        "overview": "a path",
        "phases": [{"title": "Build", "est_hours": "Wk1",
                    "items": [{"type": "build", "text": "nanoGPT",
                               "concept_refs": ["self-attention"]}],
                    "deliverable": {"kind": "repo", "text": "repo",
                                    "acceptance_criteria": ["trains"]}}],
        "sidebars": [],
    }))
    generate_curriculum(session, topic, intent, foundation, [source], llm=deps.get_llm())


def _research_search(session, rec):
    from adaptive_academy.engine.research import build_briefs

    [brief] = build_briefs("transformers", "build a GPT", 1)
    rec.queue.append(_text('[{"title": "T", "url": "https://example.org/a", "tier": 1}]'))
    deps.get_researcher().search(brief)


def _research_foundation(session, rec):
    from adaptive_academy.engine.research import synthesize_foundation
    from adaptive_academy.llm.researcher_types import RawSource

    rec.queue.append(_text(json.dumps({"overview": "o", "key_concepts": ["attention"],
                                       "prerequisite_map": {}})))
    synthesize_foundation("transformers", "build a GPT",
                          [RawSource(title="Attention Is All You Need",
                                     url="https://arxiv.org/abs/1706.03762", tier=1,
                                     summary="The transformer paper.", why="seminal",
                                     relevance=0.9, angle="foundational_papers")],
                          deps.get_llm())


SURFACES = {
    "tutor_turn": _tutor_turn,
    "assessment_grade": _assessment_grade,
    "curriculum_generation": _curriculum,
    "research_search": _research_search,
    "research_foundation": _research_foundation,
}


@pytest.mark.parametrize("surface", list(SURFACES))
def test_request_matches_snapshot(surface, session, rec):
    SURFACES[surface](session, rec)
    assert not rec.queue, "every canned response was consumed"
    actual = rec.summaries()

    stored = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}
    if os.environ.get("UPDATE_REQUEST_SNAPSHOTS") == "1":
        stored[surface] = actual
        kept = {name: calls for name, calls in sorted(stored.items()) if name in SURFACES}
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(kept, indent=2) + "\n")
        return
    assert surface in stored, (
        f"no snapshot for {surface!r}; run UPDATE_REQUEST_SNAPSHOTS=1 uv run pytest "
        "tests/test_request_snapshots.py and review the new fixture")
    assert actual == stored[surface], (
        f"the {surface!r} request changed. If intended, regenerate with "
        "UPDATE_REQUEST_SNAPSHOTS=1 uv run pytest tests/test_request_snapshots.py and review "
        "the fixture diff.")


def test_snapshot_has_no_stale_surfaces():
    stored = json.loads(SNAPSHOT.read_text())
    assert set(stored) == set(SURFACES)
