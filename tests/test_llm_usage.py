"""Every real model call records an LLMUsage row; the daily limit is enforced in code.

No network: the Anthropic SDK class is replaced by a fake whose `messages.create` returns a
canned response carrying a `usage` object, and the Agent SDK `query` by a fake async
generator yielding a ResultMessage-shaped object.
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import select

from adaptive_academy.llm import pricing, usage
from adaptive_academy.llm.researcher_types import SearchBrief
from adaptive_academy.models import LLMUsage

MODEL = "claude-sonnet-4-6"


def _usage(**kw):
    base = dict(
        input_tokens=1200,
        output_tokens=300,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        server_tool_use=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _fake_anthropic(monkeypatch, module: str, response, calls: list | None = None):
    class _Messages:
        def create(self, **kw):
            if calls is not None:
                calls.append(kw)
            return response

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr(f"adaptive_academy.llm.{module}.Anthropic", _FakeAnthropic)


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")


@pytest.fixture
def no_budget(monkeypatch):
    monkeypatch.setattr(usage.settings, "daily_budget_usd", None)


def _rows(session):
    session.expire_all()
    return session.exec(select(LLMUsage).order_by(LLMUsage.id)).all()


def _text_response(text="hello", **usage_kw):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], usage=_usage(**usage_kw)
    )


# --- recording: API-key backend -------------------------------------------------------


def test_complete_records_usage_row(session, api_key, no_budget, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    _fake_anthropic(monkeypatch, "anthropic_client", _text_response(cache_read_input_tokens=50))
    client = AnthropicLLMClient(role="reasoning")
    client._model = MODEL
    resp = client.complete("sys", [{"role": "user", "content": "hi"}], tools=[])
    assert resp.text == "hello"

    [row] = _rows(session)
    assert row.backend == "anthropic"
    assert row.model == MODEL
    assert row.role == "reasoning"
    assert row.operation == "complete"
    assert (row.input_tokens, row.output_tokens, row.cache_read_input_tokens) == (1200, 300, 50)
    assert row.web_search_requests == 0
    assert row.cost_usd == pytest.approx(
        pricing.cost_usd(MODEL, input_tokens=1200, output_tokens=300, cache_read_input_tokens=50)
    )
    assert row.feature is None  # not inside a request


def test_complete_json_records_usage_row(session, api_key, no_budget, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    resp = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="emit", input={"ok": True})],
        usage=_usage(input_tokens=10, output_tokens=20, cache_creation_input_tokens=5),
    )
    _fake_anthropic(monkeypatch, "anthropic_client", resp)
    client = AnthropicLLMClient(role="copy")
    client._model = MODEL
    out = client.complete_json("sys", [{"role": "user", "content": "x"}],
                               schema={"type": "object"}, tool_name="emit")
    assert out == {"ok": True}

    [row] = _rows(session)
    assert row.operation == "complete_json"
    assert row.role == "copy"
    assert (row.input_tokens, row.output_tokens, row.cache_creation_input_tokens) == (10, 20, 5)


def test_complete_json_records_even_when_parse_fails(session, api_key, no_budget, monkeypatch):
    # The call was billed even though no tool_use came back — it must still be counted.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    _fake_anthropic(monkeypatch, "anthropic_client", _text_response())
    client = AnthropicLLMClient()
    with pytest.raises(ValueError):
        client.complete_json("sys", [{"role": "user", "content": "x"}],
                             schema={"type": "object"}, tool_name="emit")
    assert len(_rows(session)) == 1


def test_researcher_records_web_search_requests(session, api_key, no_budget, monkeypatch):
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient

    payload = json.dumps([{"title": "t", "url": "https://example.org/a"}])
    resp = _text_response(
        text=payload, server_tool_use=SimpleNamespace(web_search_requests=4)
    )
    _fake_anthropic(monkeypatch, "anthropic_researcher", resp)
    client = AnthropicResearcherClient()
    client._model = MODEL
    out = client.search(SearchBrief(angle="a", query="q"))
    assert len(out) == 1

    [row] = _rows(session)
    assert row.operation == "research_search"
    assert row.web_search_requests == 4
    assert row.cost_usd == pytest.approx(
        pricing.cost_usd(MODEL, input_tokens=1200, output_tokens=300, web_search_requests=4)
    )


def test_unknown_model_records_tokens_with_null_cost(session, api_key, no_budget, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    _fake_anthropic(monkeypatch, "anthropic_client", _text_response())
    client = AnthropicLLMClient()
    client._model = "claude-imaginary-9"
    client.complete("sys", [{"role": "user", "content": "hi"}], tools=[])
    [row] = _rows(session)
    assert row.model == "claude-imaginary-9"
    assert row.input_tokens == 1200
    assert row.cost_usd is None


def test_missing_usage_object_still_records_a_zero_row(session, api_key, no_budget, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")])
    _fake_anthropic(monkeypatch, "anthropic_client", resp)
    AnthropicLLMClient().complete("sys", [{"role": "user", "content": "hi"}], tools=[])
    [row] = _rows(session)
    assert row.input_tokens == 0 and row.output_tokens == 0


def test_recording_failure_never_breaks_the_call(session, api_key, no_budget, monkeypatch,
                                                 caplog):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    def boom(*a, **kw):
        raise RuntimeError("disk on fire")

    _fake_anthropic(monkeypatch, "anthropic_client", _text_response(text="still here"))
    monkeypatch.setattr(usage, "_build_row", boom)
    resp = AnthropicLLMClient().complete("sys", [{"role": "user", "content": "hi"}], tools=[])
    assert resp.text == "still here"
    assert _rows(session) == []
    assert "usage" in caplog.text.lower()


def test_recording_write_failure_never_breaks_the_call(session, api_key, no_budget, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    def boom(*a, **kw):
        raise RuntimeError("writer gone")

    _fake_anthropic(monkeypatch, "anthropic_client", _text_response(text="fine"))
    monkeypatch.setattr(usage.TRACE_WRITER, "submit", boom)
    resp = AnthropicLLMClient().complete("sys", [{"role": "user", "content": "hi"}], tools=[])
    assert resp.text == "fine"
    assert _rows(session) == []


def test_recording_is_disabled_without_a_bind(api_key, no_budget, monkeypatch):
    # The autouse conftest fixture leaves no bind for tests that don't use `session`, so a
    # unit test can never write usage into the developer's real database file.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    assert usage.get_usage_bind() is None
    _fake_anthropic(monkeypatch, "anthropic_client", _text_response())
    assert AnthropicLLMClient().complete("s", [{"role": "user", "content": "x"}], []).text


def test_feature_label_comes_from_the_context(session, api_key, no_budget, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    _fake_anthropic(monkeypatch, "anthropic_client", _text_response())
    with usage.feature_context("assess"):
        AnthropicLLMClient().complete("sys", [{"role": "user", "content": "hi"}], tools=[])
    assert _rows(session)[0].feature == "assess"


def test_feature_label_survives_the_research_thread_pool(session, api_key, no_budget,
                                                         monkeypatch):
    # Research fans out on a ThreadPoolExecutor; the contextvar must follow each worker.
    from adaptive_academy.engine.fanout import fan_out_briefs
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient

    _fake_anthropic(monkeypatch, "anthropic_researcher", _text_response(text="[]"))
    researcher = AnthropicResearcherClient()
    briefs = [SearchBrief(angle=f"a{i}", query="q") for i in range(3)]
    with usage.feature_context("research"):
        fan_out_briefs(briefs, researcher, max_workers=3)
    rows = _rows(session)
    assert len(rows) == 3
    assert {r.feature for r in rows} == {"research"}


@pytest.mark.parametrize(
    ("path", "feature"),
    [
        ("/api/topics/{topic_id}/research", "research"),
        ("/api/programs/{program_id}/research", "research"),
        ("/api/conversations/{conversation_id}/messages", "tutor"),
        ("/api/concepts/{concept_id}/assess", "assess"),
        ("/api/topics/{topic_id}/curriculum", "curriculum"),
        ("/api/topics/{topic_id}/anchors", "anchors"),
        ("/api/concepts/{concept_id}/productive_failure/generate", "productive_failure"),
        ("/api/programs/{program_id}/milestones/{milestone_id}/roleplay", "roleplay"),
        ("/api/roleplay/{sid}/turns", "roleplay"),
        ("/api/paper-probe/{pid}/submit", "paper_probe"),
        ("/api/programs/{program_id}/revise", "revision"),
        ("/api/programs/{program_id}/scout", "scout"),
        ("/api/concepts/{concept_id}/teach", "teach"),
        ("/api/topics/{topic_id}/story", "story"),
        ("/api/topics/{topic_id}/sources/review", "sources"),
        ("/api/health", "health"),
        ("", None),
        (None, None),
    ],
)
def test_feature_from_route(path, feature):
    assert usage.feature_from_route(path) == feature


# --- recording: Agent SDK (subscription) backend --------------------------------------


class _FakeResult:
    def __init__(self, result="ok", is_error=False, usage=None, total_cost_usd=None):
        self.result = result
        self.is_error = is_error
        self.usage = usage
        self.total_cost_usd = total_cost_usd


_SDK_USAGE = {
    "input_tokens": 40,
    "output_tokens": 60,
    "cache_creation_input_tokens": 7,
    "cache_read_input_tokens": 900,
    "server_tool_use": {"web_search_requests": 2},
}


def test_agent_sdk_client_records_tokens_and_sdk_cost(session, monkeypatch):
    import adaptive_academy.llm.agent_sdk_client as mod

    async def fake_query(prompt, options):
        yield _FakeResult("graded", usage=_SDK_USAGE, total_cost_usd=0.0123)

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)
    resp = mod.AgentSDKLLMClient(role="reasoning").complete(
        "sys", [{"role": "user", "content": "x"}], tools=[])
    assert resp.text == "graded"

    [row] = _rows(session)
    assert row.backend == "agent_sdk"
    assert row.operation == "complete"
    assert (row.input_tokens, row.output_tokens) == (40, 60)
    assert (row.cache_creation_input_tokens, row.cache_read_input_tokens) == (7, 900)
    assert row.web_search_requests == 2
    assert row.cost_usd == pytest.approx(0.0123)


def test_agent_sdk_result_without_usage_fields_records_zeros(session, monkeypatch):
    import adaptive_academy.llm.agent_sdk_client as mod

    class _Bare:
        def __init__(self, result):
            self.result = result
            self.is_error = False

    async def fake_query(prompt, options):
        yield _Bare("ok")

    monkeypatch.setattr(mod, "ResultMessage", _Bare)
    monkeypatch.setattr(mod, "query", fake_query)
    mod.AgentSDKLLMClient().complete("sys", [{"role": "user", "content": "x"}], tools=[])
    [row] = _rows(session)
    assert row.input_tokens == 0 and row.cost_usd is None


def test_agent_sdk_error_result_is_still_recorded(session, monkeypatch):
    import adaptive_academy.llm.agent_sdk_client as mod

    async def fake_query(prompt, options):
        yield _FakeResult("overloaded", is_error=True, usage=_SDK_USAGE, total_cost_usd=0.01)

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)
    with pytest.raises(mod.AgentSDKError):
        mod.AgentSDKLLMClient().complete("sys", [{"role": "user", "content": "x"}], tools=[])
    assert len(_rows(session)) == 1


def test_agent_sdk_researcher_records(session, monkeypatch):
    import adaptive_academy.llm.agent_sdk_researcher as mod

    async def fake_query(prompt, options):
        yield _FakeResult("[]", usage=_SDK_USAGE, total_cost_usd=0.2)

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)
    mod.AgentSDKResearcherClient().search(SearchBrief(angle="a", query="q"))
    [row] = _rows(session)
    assert row.backend == "agent_sdk"
    assert row.operation == "research_search"
    assert row.web_search_requests == 2


def test_tutor_sdk_turn_records(session, monkeypatch):
    import adaptive_academy.engine.tutor_sdk as mod
    from adaptive_academy.models import Concept, Conversation, Topic, Track

    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()

    async def fake_query(prompt, options):
        yield _FakeResult("Try it first.", usage=_SDK_USAGE, total_cost_usd=0.05)

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)
    out = mod.run_tutor_turn_sdk(session, convo, "how?")
    assert out.reply == "Try it first."
    rows = [r for r in _rows(session) if r.operation == "tutor_sdk"]
    assert len(rows) == 1 and rows[0].backend == "agent_sdk"


# --- daily spending limit -------------------------------------------------------------


def _spend(session, usd, *, backend="anthropic", when=None):
    session.add(LLMUsage(backend=backend, model=MODEL, role="reasoning", operation="complete",
                         cost_usd=usd, created_at=when or datetime.now(timezone.utc)))
    session.commit()


def test_under_the_limit_the_call_goes_through(session, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    monkeypatch.setattr(usage.settings, "daily_budget_usd", 1.0)
    _spend(session, 0.40)
    _fake_anthropic(monkeypatch, "anthropic_client", _text_response())
    assert AnthropicLLMClient().complete("s", [{"role": "user", "content": "x"}], []).text


@pytest.mark.parametrize("spent", [1.0, 1.5])
def test_at_or_over_the_limit_raises_before_any_call(session, api_key, monkeypatch, spent):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient

    monkeypatch.setattr(usage.settings, "daily_budget_usd", 1.0)
    _spend(session, spent)
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", _text_response(), calls)
    _fake_anthropic(monkeypatch, "anthropic_researcher", _text_response(text="[]"), calls)

    client = AnthropicLLMClient()
    with pytest.raises(usage.BudgetExceededError) as exc:
        client.complete("s", [{"role": "user", "content": "x"}], [])
    assert exc.value.spent_usd == pytest.approx(spent)
    assert exc.value.limit_usd == pytest.approx(1.0)
    with pytest.raises(usage.BudgetExceededError):
        client.complete_json("s", [{"role": "user", "content": "x"}],
                             schema={"type": "object"}, tool_name="emit")
    with pytest.raises(usage.BudgetExceededError):
        AnthropicResearcherClient().search(SearchBrief(angle="a", query="q"))
    assert calls == []  # nothing reached the (fake) network


def test_budget_counts_only_today_and_only_api_key_spend(session, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    monkeypatch.setattr(usage.settings, "daily_budget_usd", 1.0)
    _spend(session, 5.0, when=datetime.now(timezone.utc) - timedelta(days=2))
    _spend(session, 5.0, backend="agent_sdk")  # subscription, not the key
    _spend(session, None)  # unknown price
    assert usage.spent_today_usd() == pytest.approx(0.0)
    _fake_anthropic(monkeypatch, "anthropic_client", _text_response())
    assert AnthropicLLMClient().complete("s", [{"role": "user", "content": "x"}], []).text


def test_budget_exceeded_error_is_not_swallowed_by_the_research_fanout(session, api_key,
                                                                       monkeypatch):
    from adaptive_academy.engine.fanout import fan_out_with_retry
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient

    monkeypatch.setattr(usage.settings, "daily_budget_usd", 1.0)
    _spend(session, 2.0)
    _fake_anthropic(monkeypatch, "anthropic_researcher", _text_response(text="[]"))
    with pytest.raises(usage.BudgetExceededError):
        fan_out_with_retry([SearchBrief(angle="a", query="q")], AnthropicResearcherClient(), 2)


def test_agent_sdk_calls_are_not_blocked_by_the_limit(session, monkeypatch):
    import adaptive_academy.llm.agent_sdk_client as mod

    monkeypatch.setattr(usage.settings, "daily_budget_usd", 1.0)
    _spend(session, 50.0)

    async def fake_query(prompt, options):
        yield _FakeResult("subscription ok")

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)
    resp = mod.AgentSDKLLMClient().complete("s", [{"role": "user", "content": "x"}], tools=[])
    assert resp.text == "subscription ok"


def test_budget_read_failure_fails_open(api_key, monkeypatch, caplog):
    # A broken usage store must not take every LLM feature down with it.
    monkeypatch.setattr(usage.settings, "daily_budget_usd", 1.0)

    def broken():
        raise RuntimeError("db gone")

    monkeypatch.setattr(usage, "spent_today_usd", broken)
    usage.check_budget()  # does not raise
    assert "budget" in caplog.text.lower()


def test_file_database_rows_are_written_off_the_calling_thread(tmp_path, api_key, no_budget,
                                                               monkeypatch):
    # The production shape: a pooled file engine → the row is queued to the one bounded
    # background writer, so the call never waits on SQLite's write lock.
    from sqlmodel import Session, SQLModel, create_engine

    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    engine = create_engine(f"sqlite:///{tmp_path / 'usage.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    usage.set_usage_bind(engine)
    _fake_anthropic(monkeypatch, "anthropic_client", _text_response())
    AnthropicLLMClient().complete("s", [{"role": "user", "content": "x"}], [])
    assert usage.TRACE_WRITER.flush()
    with Session(engine) as s:
        assert len(s.exec(select(LLMUsage)).all()) == 1
    engine.dispose()


def test_local_day_start_is_local_midnight_in_utc():
    now = datetime(2026, 10, 19, 15, 30, tzinfo=timezone(timedelta(hours=-7)))
    start = usage.local_day_start(now)
    assert start == datetime(2026, 10, 19, 7, 0, tzinfo=timezone.utc)
