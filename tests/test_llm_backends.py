"""AA_LLM_BACKEND selects who the API-key clients talk to; each backend has its own key,
endpoint, auth style and default models. The model catalog holds per-family differences."""

import pytest

from adaptive_academy.llm import backends, keys, model_catalog
from adaptive_academy.llm.registry import get_model, resolved_models
from adaptive_academy.settings import settings


@pytest.fixture(autouse=True)
def _default_models(monkeypatch):
    # Blank = the backend's default, whatever the developer's .env says.
    monkeypatch.setattr(settings, "reasoning_model", "")
    monkeypatch.setattr(settings, "copy_model", "")


# --- backend selection ------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "name"), [
    (None, "anthropic"), ("", "anthropic"), ("anthropic", "anthropic"),
    ("openrouter", "openrouter"), (" OpenRouter ", "openrouter"),
    ("agent_sdk", "agent_sdk"), ("AGENT_SDK", "agent_sdk"),
    ("something-else", "anthropic"),
])
def test_backend_name_from_env(monkeypatch, raw, name):
    if raw is None:
        monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    else:
        monkeypatch.setenv("AA_LLM_BACKEND", raw)
    assert backends.current_backend_name() == name


def test_openrouter_backend_config(monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    b = backends.api_backend()
    assert b.name == "openrouter"
    assert b.provider == "OpenRouter"
    assert b.key_env == "OPENROUTER_API_KEY"
    assert b.base_url == "https://openrouter.ai/api"
    assert b.bearer_auth is True
    assert b.reports_cost is True
    assert b.extra_body == {"provider": {"data_collection": "deny"}}


def test_anthropic_backend_config(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    b = backends.api_backend()
    assert (b.name, b.provider, b.key_env) == ("anthropic", "Anthropic", "ANTHROPIC_API_KEY")
    assert b.base_url is None  # the SDK default
    assert b.bearer_auth is False
    assert b.reports_cost is False
    assert b.extra_body is None


def test_agent_sdk_api_key_clients_stay_on_anthropic(monkeypatch):
    # The Agent SDK's bridge (tool turns) builds an API-key client: that is the Anthropic one.
    monkeypatch.setenv("AA_LLM_BACKEND", "agent_sdk")
    assert backends.api_backend().name == "anthropic"


# --- keys -------------------------------------------------------------------------------


def test_openrouter_key_checks(monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    b = backends.api_backend()
    for value in ("", "   ", "sk-or-xxxxx", "sk-or-...", "sk-or-v1-xxxxx", "sk-or-…"):
        monkeypatch.setenv("OPENROUTER_API_KEY", value)
        assert not keys.key_configured(b)
        with pytest.raises(keys.MissingAPIKeyError) as caught:
            keys.require_api_key(b)
        assert "OPENROUTER_API_KEY" in str(caught.value)
        assert "ANTHROPIC_API_KEY" not in str(caught.value)
        assert caught.value.env_var == "OPENROUTER_API_KEY"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert not keys.key_configured(b)
    monkeypatch.setenv("OPENROUTER_API_KEY", "  sk-or-v1-real  ")
    assert keys.require_api_key(b) == "sk-or-v1-real"


def test_an_anthropic_key_does_not_satisfy_openrouter(monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-looking")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert not keys.key_configured(backends.api_backend())


def test_missing_key_detail_names_the_variable():
    assert "OPENROUTER_API_KEY" in keys.missing_key_detail("OPENROUTER_API_KEY")
    assert keys.missing_key_detail("ANTHROPIC_API_KEY") == keys.MISSING_KEY_DETAIL
    assert keys.MissingAPIKeyError().env_var == "ANTHROPIC_API_KEY"


# --- models per backend -----------------------------------------------------------------


def test_default_models_per_backend(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    assert resolved_models() == {"reasoning": "claude-sonnet-5-5", "copy": "claude-haiku-5-5"}
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    assert resolved_models() == {"reasoning": "anthropic/claude-sonnet-5.5",
                                 "copy": "anthropic/claude-haiku-5.5"}


def test_overrides_still_win_on_openrouter(monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    monkeypatch.setattr(settings, "reasoning_model", "deepseek/deepseek-v4")
    assert get_model("reasoning") == "deepseek/deepseek-v4"
    assert get_model("copy") == "anthropic/claude-haiku-5.5"


# --- model catalog ----------------------------------------------------------------------


@pytest.mark.parametrize("model", [
    "claude-sonnet-5-5", "claude-haiku-4-5-20251001", "anthropic/claude-sonnet-5.5",
    "anthropic/claude-haiku-5.5", "Anthropic/Claude-Opus-5.5", "anthropic/claude-opus-5.5:beta",
])
def test_claude_models_are_fully_supported(model):
    caps = model_catalog.capabilities(model)
    assert caps.family == "anthropic"
    assert caps.strict_tools and caps.anthropic_web_search and caps.thinking_replay
    assert caps.structured_output == model_catalog.STRUCTURED_STRICT_TOOL
    assert not caps.experimental


@pytest.mark.parametrize("model", [
    "deepseek/deepseek-v4", "openai/gpt-5.6", "google/gemini-3-pro", "mystery", "",
])
def test_other_models_are_experimental(model):
    caps = model_catalog.capabilities(model)
    assert caps.experimental
    assert not caps.anthropic_web_search
    assert not caps.thinking_replay
    assert not caps.strict_tools
    # No tools at all: output_config.format (llm/anthropic_client.py), after a live run where
    # DeepSeek wrote its native tool-call markup as text instead of a tool_use block.
    assert caps.structured_output == model_catalog.STRUCTURED_JSON_SCHEMA


def test_structured_output_modes_are_the_three_known_ones():
    modes = {f.structured_output for f in (*model_catalog.FAMILIES.values(),
                                           model_catalog.OTHER)}
    assert modes == {model_catalog.STRUCTURED_STRICT_TOOL, model_catalog.STRUCTURED_TOOL,
                     model_catalog.STRUCTURED_JSON_SCHEMA}
    for caps in (*model_catalog.FAMILIES.values(), model_catalog.OTHER):
        assert caps.strict_tools == (caps.structured_output
                                     == model_catalog.STRUCTURED_STRICT_TOOL)


def test_web_search_tool_follows_the_catalog():
    assert model_catalog.web_search_tool("anthropic/claude-sonnet-5.5", 5) == {
        "type": "web_search_20250305", "name": "web_search", "max_uses": 5}
    assert model_catalog.web_search_tool("claude-sonnet-5-5", 3) == {
        "type": "web_search_20250305", "name": "web_search", "max_uses": 3}
    assert model_catalog.web_search_tool("deepseek/deepseek-v4", 5) == {
        "type": "openrouter:web_search", "parameters": {"max_uses": 5}}


def test_experimental_models_lists_configured_ones(monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    assert model_catalog.experimental_models() == []
    monkeypatch.setattr(settings, "copy_model", "deepseek/deepseek-v4")
    assert model_catalog.experimental_models() == ["deepseek/deepseek-v4"]


def test_the_missing_key_message_names_the_right_restart_step(monkeypatch):
    from adaptive_academy.llm.keys import missing_key_detail

    monkeypatch.delenv("AA_IN_CONTAINER", raising=False)
    host = missing_key_detail("ANTHROPIC_API_KEY")
    assert "just api" in host and "just up" not in host
    monkeypatch.setenv("AA_IN_CONTAINER", "1")
    docker = missing_key_detail("ANTHROPIC_API_KEY")
    assert "just up" in docker and "just api" not in docker
    assert "—" not in host and "—" not in docker
