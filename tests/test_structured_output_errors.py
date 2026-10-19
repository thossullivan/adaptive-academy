"""A structured completion that can't produce its tool call is a legible 502, never a bare
500 (curriculum, scout) or a misleading 400 (program research / revision), and the run
guard it ran under is released so the user can simply retry."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse, StructuredOutputError
from adaptive_academy.models import (
    Milestone,
    Program,
    ProgramIntent,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
)

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"]}


# --- the client raises the typed error ----------------------------------------------


def _fake_anthropic(monkeypatch, responses: list):
    queue = list(responses)

    class _Messages:
        def create(self, **kw):
            return queue.pop(0)

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr("adaptive_academy.llm.anthropic_client.Anthropic", _FakeAnthropic)


def _resp(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal", "model_context_window_exceeded"])
def test_complete_json_stop_reasons_raise_structured_output_error(api_key, monkeypatch,
                                                                  stop_reason):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    _fake_anthropic(monkeypatch, [_resp(stop_reason=stop_reason)])
    with pytest.raises(StructuredOutputError) as exc:
        AnthropicLLMClient().complete_json("s", [{"role": "user", "content": "x"}],
                                           schema=SCHEMA, tool_name="emit")
    assert exc.value.reason == stop_reason
    assert isinstance(exc.value, ValueError)  # existing `except ValueError` keeps working


def test_complete_json_no_tool_use_twice_raises_structured_output_error(api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    text = SimpleNamespace(type="text", text="prose")
    _fake_anthropic(monkeypatch, [_resp(text), _resp(text)])
    with pytest.raises(StructuredOutputError) as exc:
        AnthropicLLMClient().complete_json("s", [{"role": "user", "content": "x"}],
                                           schema=SCHEMA, tool_name="emit")
    assert exc.value.reason == "no_tool_use"


def test_detail_says_what_happened_and_that_retrying_may_help():
    assert "too long" in StructuredOutputError("max_tokens").detail
    for reason in ("max_tokens", "refusal", "model_context_window_exceeded", "no_tool_use"):
        detail = StructuredOutputError(reason).detail
        assert "retry" in detail.lower(), detail


# --- the routes map it to 502 and release their run guards ---------------------------


class _FailingStructuredLLM:
    """complete_json always fails the way the real client does on a truncated answer."""

    def __init__(self, reason: str = "max_tokens"):
        self.reason = reason
        self.calls = 0

    def complete(self, system, messages, tools):
        return LLMResponse(text="{}")

    def complete_json(self, system, messages, *, schema, tool_name):
        self.calls += 1
        raise StructuredOutputError(self.reason)


def _client(session: Session, llm) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "phd_curricula": [RawSource(title="Quals", url="https://mit.edu/q", tier=1)],
        "whats_new": [RawSource(title="MoE", url="https://e.com/moe", tier=1)],
    })
    return TestClient(app)


def _assert_legible_502(r, *, needle: str = "too long"):
    assert r.status_code == 502, r.text
    detail = r.json()["detail"]
    assert needle in detail
    assert "retry" in detail.lower()


def test_curriculum_structured_failure_is_502_and_releases_the_guard(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(TopicIntent(topic_id=topic.id, goal="g"))
    session.add(TopicFoundation(topic_id=topic.id, overview="o", key_concepts=["la"],
                                prerequisite_map={}))
    session.add(SourceDoc(topic_id=topic.id, title="S", url="u", tier=1, status="accepted"))
    session.commit()
    llm = _FailingStructuredLLM()
    client = _client(session, llm)

    _assert_legible_502(client.post(f"/api/topics/{topic.id}/curriculum"))
    # Not 409 "already running": the guard was released on the error.
    _assert_legible_502(client.post(f"/api/topics/{topic.id}/curriculum"))
    assert llm.calls == 2


def _program(session: Session, *, with_milestone: bool = True) -> Program:
    program = Program(title="P", goal_statement="g")
    session.add(program)
    session.flush()
    session.add(ProgramIntent(program_id=program.id, focus_area="f",
                              prior_knowledge="p", weekly_time_budget="1h", horizon="1y",
                              target_depth="phd"))
    if with_milestone:  # a proposal already exists (scout / revision need one)
        session.add(Milestone(program_id=program.id, title="M"))
    session.commit()
    return program


def test_scout_structured_failure_is_502_and_releases_the_guard(session):
    from adaptive_academy.models import Chunk

    program = _program(session)
    session.add(Chunk(kind="vault_note", source_ref="file:///vault/x.md", text="Sparse ideas",
                      context="Sparse retrieval", content_hash="scout-x"))
    session.commit()
    llm = _FailingStructuredLLM("refusal")
    client = _client(session, llm)

    r = client.post(f"/api/programs/{program.id}/scout")
    _assert_legible_502(r, needle="declined")
    _assert_legible_502(client.post(f"/api/programs/{program.id}/scout"), needle="declined")
    assert llm.calls == 2


def test_program_research_structured_failure_is_502_not_400(session):
    program = _program(session, with_milestone=False)
    client = _client(session, _FailingStructuredLLM())
    _assert_legible_502(client.post(f"/api/programs/{program.id}/research"))


def test_program_revision_structured_failure_is_502_not_400(session):
    program = _program(session)
    llm = _FailingStructuredLLM("no_tool_use")
    client = _client(session, llm)
    r = client.post(f"/api/programs/{program.id}/revise")
    _assert_legible_502(r, needle="structured")
    # The revision run guard was released too.
    _assert_legible_502(client.post(f"/api/programs/{program.id}/revise"), needle="structured")


def test_plain_value_error_from_program_research_is_still_400(session):
    # Only the structured-output failure moves to 502; real input problems stay 400.
    program = _program(session, with_milestone=False)
    llm = _FailingStructuredLLM()
    client = _client(session, llm)
    client.app.dependency_overrides[get_llm] = lambda: _ProposalLLM()
    assert client.post(f"/api/programs/{program.id}/research").status_code == 200
    r = client.post(f"/api/programs/{program.id}/research")
    assert r.status_code == 400
    assert "already has a proposal" in r.json()["detail"]


class _ProposalLLM:
    def complete(self, system, messages, tools):
        return LLMResponse(text=json.dumps({"milestones": [
            {"title": "M1", "success_criteria": "s", "depends_on": [],
             "topics": [{"title": "T1", "why": "w"}]}]}))
