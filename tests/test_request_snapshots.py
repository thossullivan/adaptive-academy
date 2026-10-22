"""Pin the exact request the main call surfaces send to the Anthropic API.

Pinned surfaces (see SURFACES below): a two-turn tutor conversation with a tool step (and
the solution guard's attempt check on its log_attempt), an
assessment (rubric then grade), curriculum generation, a research search, the research
foundation, a two-turn roleplay persona, a teach-back grade, the paper-probe director, and
the tutor's solution guard with its regeneration. Other engine calls are not pinned here.
Each surface is pinned twice: on the default Anthropic backend (keyed by the surface name) and
on AA_LLM_BACKEND=openrouter (keyed "openrouter/<surface>"), where the endpoint, the model
slugs, the auth header kind and OpenRouter's provider preference differ.

A change to any of their prompts, schemas, tools, the model, a parameter, or where the
prompt-cache breakpoints sit changes tests/fixtures/request_snapshots.json, so it shows up
as a reviewed diff instead of slipping through. Per call it records: the usage operation,
role and model, max_tokens, a sha256 and length of EACH system block (so text moving across
the cache breakpoint shows), a sha256 of the messages, each tool's name with a sha256 of its
full definition, tool_choice, any other request parameters (OpenRouter's `provider`
preference arrives here as `extra_body`), every cache_control location, and the client's
endpoint (base URL, and whether the key goes as x-api-key or Authorization: Bearer).

The engine functions run against the real AnthropicLLMClient / AnthropicResearcherClient
from api/deps, whose SDK `messages.create` is replaced by a fake that records the kwargs and
returns canned responses. No network. The date in the system prompt is frozen and the models
are pinned to the defaults, so the hashes are stable.

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


def _summarise(kw, usage_call, endpoint) -> dict:
    system = kw.get("system")
    blocks = [system] if isinstance(system, str) else [b["text"] for b in system]
    return {
        "endpoint": endpoint,
        "operation": usage_call["operation"],
        "role": usage_call["role"],
        "model": kw["model"],
        "max_tokens": kw["max_tokens"],
        # One entry per system block, in order: [stable text, today's date].
        "system": [{"sha256": _sha(text), "chars": len(text)} for text in blocks],
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
        self.endpoints: list[dict] = []
        self.usage: list[dict] = []
        self.queue: list = []

    def summaries(self) -> list[dict]:
        assert len(self.calls) == len(self.usage), "every call records its usage once"
        return [_summarise(kw, u, e)
                for kw, u, e in zip(self.calls, self.usage, self.endpoints)]


def _endpoint(client_kw) -> dict:
    """Where the client sends requests and how it authenticates, never the key itself."""
    if client_kw.get("auth_token"):
        auth = "authorization-bearer"
    elif client_kw.get("api_key"):
        auth = "x-api-key"
    else:
        auth = "none"
    headers = client_kw.get("default_headers") or {}
    return {
        "base_url": client_kw.get("base_url"),
        "auth": auth,
        "drops_x_api_key": any(k.lower() == "x-api-key" for k in headers),
    }


def _resp(*blocks, stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0,
                            cache_read_input_tokens=0, server_tool_use=None)
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage)


def _text(text):
    return _resp(TextBlock(type="text", text=text))


def _tool(name, payload, id_="toolu_01"):
    return _resp(ToolUseBlock(type="tool_use", id=id_, name=name, input=payload),
                 stop_reason="tool_use")


BACKENDS = ("anthropic", "openrouter")


@pytest.fixture(params=BACKENDS)
def rec(request, monkeypatch):
    from adaptive_academy.settings import settings

    recorder = _Recorder()
    recorder.backend = request.param

    class _Messages:
        def __init__(self, endpoint):
            self.endpoint = endpoint

        def create(self, **kw):
            recorder.calls.append(json.loads(json.dumps(kw)))  # a copy, as sent
            recorder.endpoints.append(self.endpoint)
            return recorder.queue.pop(0)

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages(_endpoint(kw))

    def _record_usage(**kw):
        recorder.usage.append({"operation": kw["operation"], "role": kw["role"]})

    for module in ("anthropic_client", "anthropic_researcher"):
        monkeypatch.setattr(f"adaptive_academy.llm.{module}.Anthropic", _FakeAnthropic)
        monkeypatch.setattr(f"adaptive_academy.llm.{module}.record_usage", _record_usage)
    monkeypatch.setattr(today, "local_now", lambda: FROZEN_NOW)
    if request.param == "openrouter":
        monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    else:
        monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    # Pin the defaults (llm/backends.py, per backend), whatever the developer's .env says.
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
    from adaptive_academy.engine.solution_guard import GUARD_TOOL
    from adaptive_academy.engine.tutor import run_tutor_turn

    topic, concept = _concept(session)
    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    rec.queue += [
        _tool("log_attempt", {"summary": "softmax over QK^T"}),
        # The solution guard's attempt check (copy role, no draft) confirms the attempt.
        _tool(GUARD_TOOL, {"gives_away_solution": False, "learner_attempted": True,
                           "reason": "a formula with its parts named"}, id_="toolu_a1"),
        _text("Good start. Why divide by sqrt(d_k)?"),
        _text("Right: it keeps the softmax out of saturation."),
    ]
    llm = deps.get_llm()
    # Two learner turns: the first runs a tool step, the second resends the history.
    run_tutor_turn(session, convo, "Attention is softmax(QK^T)V: each query scores every "
                   "key, and the weights mix the values.", llm, guard_llm=deps.get_guard_llm())
    run_tutor_turn(session, convo, "To keep the dot products from growing with d_k.", llm,
                   guard_llm=deps.get_guard_llm())


def _tutor_solution_guard(session, rec):
    from adaptive_academy.engine.solution_guard import GUARD_TOOL
    from adaptive_academy.engine.tutor import run_tutor_turn

    topic, concept = _concept(session)
    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    rec.queue += [
        _text("Divide QK^T by sqrt(d_k), softmax each row, then multiply by V."),
        _tool(GUARD_TOOL, {"gives_away_solution": True, "reason": "states the computation"},
              id_="toolu_g1"),
        _text("What does each row of QK^T measure?"),
        _tool(GUARD_TOOL, {"gives_away_solution": False, "reason": "asks a question"},
              id_="toolu_g2"),
    ]
    # A pre-attempt reply that leaks: the guard check (copy role), the append-only
    # regeneration (reasoning role), then the check on the regenerated hint.
    run_tutor_turn(session, convo, "Just tell me how attention works.", deps.get_llm(),
                   guard_llm=deps.get_guard_llm())


def _assessment_grade(session, rec):
    from adaptive_academy.engine.assess import assess_concept

    _, concept = _concept(session)
    rec.queue += [
        _text(json.dumps({"criteria": ["names QK^T"], "must_include": ["softmax"],
                          "strong_signs": [], "weak_signs": [], "source_refs": []})),
        _text(json.dumps({"score": 0.6, "verdict": "partial", "gaps": ["no scaling"],
                          "mechanism_present": True,
                          "missing_required": [], "misconceptions_committed": []})),
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


def _milestone(session, concept_name):
    """A program milestone with one load-bearing concept (roleplay / paper probe need it)."""
    from adaptive_academy.models import Milestone, Program, ProgramTopicLink

    program = Program(title="PhD", goal_statement="g")
    session.add(program)
    session.commit()
    milestone = Milestone(program_id=program.id, title="Transformers",
                          success_criteria="explain and critique the paper")
    session.add(milestone)
    session.commit()
    topic = Topic(title="Transformers")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name=concept_name, is_load_bearing=True)
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="low"))
    session.add(ProgramTopicLink(milestone_id=milestone.id, topic_id=topic.id,
                                 status="started"))
    session.commit()
    return program, milestone, concept


def _roleplay_persona(session, rec):
    # The other multi-turn caller of `complete` (no tools): the second turn resends history.
    from adaptive_academy.engine.roleplay import run_roleplay_turn
    from adaptive_academy.models import RoleplaySession

    program, milestone, _ = _milestone(session, "SPIN questioning")
    rp = RoleplaySession(program_id=program.id, milestone_id=milestone.id, status="active",
                         persona_brief={"persona": "Skeptical VP of Engineering",
                                        "goal": "avoid committing", "situation": "cold call",
                                        "hidden_objections": ["already have a vendor"],
                                        "win_conditions": ["agree to a technical eval"],
                                        "difficulty": "high"})
    session.add(rp)
    session.commit()
    rec.queue += [_text("Who is this, and why now?"), _text("We already have a vendor.")]
    llm = deps.get_llm()
    run_roleplay_turn(session, rp, "Hi, I'm calling about your build pipeline.", llm=llm)
    run_roleplay_turn(session, rp, "What does a slow build cost your team?", llm=llm)


def _teach(session, rec):
    from adaptive_academy.engine.teach import grade_teaching

    _, concept = _concept(session)
    rec.queue.append(_text(json.dumps({"score": 0.7, "feedback": "clear",
                                       "strengths": ["intuition"], "gaps": ["scaling"]})))
    grade_teaching(session, concept, "Each token asks every other token how relevant it is.",
                   llm=deps.get_llm())


def _paper_probe_director(session, rec):
    from adaptive_academy.engine.paper_probe import direct
    from adaptive_academy.models import PaperProbe

    program, milestone, concept = _milestone(session, "Self-attention")
    probe = PaperProbe(program_id=program.id, milestone_id=milestone.id,
                       paper_title="Attention Is All You Need",
                       paper_text="We propose the Transformer, based solely on attention.",
                       source="arxiv", status="drafting")
    session.add(probe)
    session.commit()
    rec.queue.append(_text(json.dumps({"questions": [
        {"axis": "method", "prompt": "How are attention weights computed?",
         "concept_ids": [concept.id]}]})))
    direct(session, probe, llm=deps.get_llm())


SURFACES = {
    "tutor_turn": _tutor_turn,
    "tutor_solution_guard": _tutor_solution_guard,
    "assessment_grade": _assessment_grade,
    "curriculum_generation": _curriculum,
    "research_search": _research_search,
    "research_foundation": _research_foundation,
    "roleplay_persona": _roleplay_persona,
    "teach_grade": _teach,
    "paper_probe_director": _paper_probe_director,
}


def _key(backend: str, surface: str) -> str:
    return surface if backend == "anthropic" else f"{backend}/{surface}"


ALL_KEYS = {_key(b, s) for b in BACKENDS for s in SURFACES}


@pytest.mark.parametrize("surface", list(SURFACES))
def test_request_matches_snapshot(surface, session, rec):
    SURFACES[surface](session, rec)
    assert not rec.queue, "every canned response was consumed"
    actual = rec.summaries()
    key = _key(rec.backend, surface)

    stored = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}
    if os.environ.get("UPDATE_REQUEST_SNAPSHOTS") == "1":
        stored[key] = actual
        kept = {name: calls for name, calls in sorted(stored.items()) if name in ALL_KEYS}
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(kept, indent=2) + "\n")
        return
    assert key in stored, (
        f"no snapshot for {key!r}; run UPDATE_REQUEST_SNAPSHOTS=1 uv run pytest "
        "tests/test_request_snapshots.py and review the new fixture")
    assert actual == stored[key], (
        f"the {key!r} request changed. If intended, regenerate with "
        "UPDATE_REQUEST_SNAPSHOTS=1 uv run pytest tests/test_request_snapshots.py and review "
        "the fixture diff.")


def test_snapshot_has_no_stale_surfaces():
    stored = json.loads(SNAPSHOT.read_text())
    assert set(stored) == ALL_KEYS


def test_openrouter_snapshots_differ_only_where_the_backend_does():
    # Same prompts, tools and cache breakpoints on both backends; only the endpoint, the
    # model slug and OpenRouter's provider preference change.
    stored = json.loads(SNAPSHOT.read_text())
    slugs = {"claude-sonnet-5-5": "anthropic/claude-sonnet-5.5",
             "claude-haiku-5-5": "anthropic/claude-haiku-5.5"}
    for surface in SURFACES:
        direct, routed = stored[surface], stored[_key("openrouter", surface)]
        assert len(direct) == len(routed)
        for a, b in zip(direct, routed):
            assert a["endpoint"] == {"base_url": "https://api.anthropic.com", "auth": "x-api-key",
                                     "drops_x_api_key": False}
            assert b["endpoint"] == {"base_url": "https://openrouter.ai/api",
                                     "auth": "authorization-bearer", "drops_x_api_key": True}
            assert b["model"] == slugs[a["model"]]
            assert "extra_body" not in a["other_params"]
            assert b["other_params"] == {
                **a["other_params"], "extra_body": {"provider": {"data_collection": "deny"}}}
            ignore = {"endpoint", "model", "other_params"}
            assert {k: v for k, v in a.items() if k not in ignore} == {
                k: v for k, v in b.items() if k not in ignore}
