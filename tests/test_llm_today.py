"""Today's date goes into every system prompt a real client sends.

Without it a model guesses the day (a sibling project's tutor wrote "Today is Thursday" on a
Friday). The line is appended at the END of the system text so everything before it stays a
stable, cacheable prefix. The clock is `llm.today.local_now`, patched here; no network.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from adaptive_academy.llm import today
from adaptive_academy.llm.researcher_types import SearchBrief

FRIDAY = datetime(2026, 10, 23, 9, 30, tzinfo=timezone.utc)
LINE = "Today's date is 2026-10-23 (Friday)."


@pytest.fixture
def friday(monkeypatch):
    monkeypatch.setattr(today, "local_now", lambda: FRIDAY)


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")


def _fake_anthropic(monkeypatch, module, responses, calls):
    queue = list(responses)

    class _Messages:
        def create(self, **kw):
            calls.append(kw)
            return queue.pop(0)

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr(f"adaptive_academy.llm.{module}.Anthropic", _FakeAnthropic)


def _resp(*blocks, stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=1, output_tokens=1, cache_creation_input_tokens=0,
                            cache_read_input_tokens=0, server_tool_use=None)
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage)


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _system_text(kw) -> str:
    system = kw["system"]
    return system if isinstance(system, str) else "".join(b["text"] for b in system)


# --- the helper -----------------------------------------------------------------------


def test_today_line_is_iso_date_plus_weekday(friday):
    assert today.today_line() == LINE


def test_today_line_takes_an_explicit_moment():
    assert today.today_line(datetime(2026, 1, 1, 12)) == "Today's date is 2026-01-01 (Thursday)."


def test_with_today_appends_the_line_at_the_end(friday):
    assert today.with_today("You are a tutor.") == f"You are a tutor.\n\n{LINE}"


def test_local_now_is_timezone_aware():
    assert today.local_now().tzinfo is not None


# --- every client that sends a system prompt -------------------------------------------


def test_anthropic_complete_ends_its_system_prompt_with_today(friday, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [_resp(_text("hi"))], calls)
    AnthropicLLMClient().complete("SYS", [{"role": "user", "content": "x"}], [])
    text = _system_text(calls[0])
    assert text.startswith("SYS")
    assert text.endswith(LINE)


def test_anthropic_complete_json_ends_its_system_prompt_with_today(friday, api_key,
                                                                   monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    tool = SimpleNamespace(type="tool_use", id="t", name="emit", input={"a": "b"})
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [_resp(tool, stop_reason="tool_use")],
                    calls)
    AnthropicLLMClient().complete_json(
        "SYS", [{"role": "user", "content": "x"}],
        schema={"type": "object", "properties": {"a": {"type": "string"}}}, tool_name="emit")
    text = _system_text(calls[0])
    assert text.startswith("SYS")
    assert "emit" in text  # the structured-tool instruction is still there, before the date
    assert text.endswith(LINE)


def test_anthropic_researcher_ends_its_system_prompt_with_today(friday, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
    from adaptive_academy.prompts import RESEARCH_SEARCH

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_researcher", [_resp(_text("[]"))], calls)
    AnthropicResearcherClient().search(SearchBrief(angle="a", query="q"))
    text = _system_text(calls[0])
    assert text.startswith(RESEARCH_SEARCH)
    assert text.endswith(LINE)


class _FakeResult:
    def __init__(self, result):
        self.result = result
        self.is_error = False


def test_agent_sdk_client_ends_its_system_prompt_with_today(friday, monkeypatch):
    import adaptive_academy.llm.agent_sdk_client as mod

    seen = {}

    async def fake_query(prompt, options):
        seen["system"] = options.system_prompt
        yield _FakeResult("ok")

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)
    mod.AgentSDKLLMClient().complete("SYS", [{"role": "user", "content": "x"}], [])
    assert seen["system"] == f"SYS\n\n{LINE}"


def test_agent_sdk_researcher_ends_its_system_prompt_with_today(friday, monkeypatch):
    import adaptive_academy.llm.agent_sdk_researcher as mod
    from adaptive_academy.prompts import RESEARCH_SEARCH

    seen = {}

    async def fake_query(prompt, options):
        seen["system"] = options.system_prompt
        yield _FakeResult("[]")

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)
    mod.AgentSDKResearcherClient().search(SearchBrief(angle="a", query="q"))
    assert seen["system"] == f"{RESEARCH_SEARCH}\n\n{LINE}"


def test_agent_sdk_bridge_to_the_api_key_client_adds_the_date_once(friday, api_key,
                                                                   monkeypatch):
    # A tool-using call in agent_sdk mode bridges to AnthropicLLMClient, which adds the date
    # itself; the bridge must not add a second line.
    import adaptive_academy.llm.agent_sdk_client as mod

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [_resp(_text("hi"))], calls)
    mod.AgentSDKLLMClient().complete("SYS", [{"role": "user", "content": "x"}],
                                     [{"name": "t", "input_schema": {"type": "object"}}])
    assert _system_text(calls[0]).count("Today's date is") == 1


def test_tutor_sdk_ends_its_system_prompt_with_today(friday, session, monkeypatch):
    # The subscription tutor builds its own Agent SDK options (engine/tutor_sdk.py); the
    # tutor is where a wrong weekday would actually be said to the learner.
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

    seen = {}

    async def fake_query(prompt, options):
        seen["system"] = options.system_prompt
        yield _FakeResult("What does softmax normalise?")

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)
    mod.run_tutor_turn_sdk(session, convo, "explain softmax")
    assert seen["system"].endswith(f"\n\n{LINE}")
    assert seen["system"].count("Today's date is") == 1
