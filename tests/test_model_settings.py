"""Model ids are configurable (AA_MODEL_REASONING / AA_MODEL_COPY), resolved at call time."""

import pytest

from adaptive_academy.llm.registry import get_model
from adaptive_academy.settings import Settings, settings


@pytest.fixture(autouse=True)
def _no_model_env(monkeypatch):
    monkeypatch.delenv("AA_MODEL_REASONING", raising=False)
    monkeypatch.delenv("AA_MODEL_COPY", raising=False)


def test_defaults_are_the_current_claude_5_family():
    s = Settings(_env_file=None)
    assert s.reasoning_model == "claude-sonnet-5-5"
    assert s.copy_model == "claude-haiku-5-5"


def test_env_overrides_each_role(monkeypatch):
    monkeypatch.setenv("AA_MODEL_REASONING", "claude-opus-5-5")
    monkeypatch.setenv("AA_MODEL_COPY", "claude-sonnet-5-5")
    s = Settings(_env_file=None)
    assert s.reasoning_model == "claude-opus-5-5"
    assert s.copy_model == "claude-sonnet-5-5"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_env_falls_back_to_default(monkeypatch, blank):
    # compose passes `${AA_MODEL_REASONING:-}` through, so an unset var arrives as "".
    monkeypatch.setenv("AA_MODEL_REASONING", blank)
    monkeypatch.setenv("AA_MODEL_COPY", blank)
    s = Settings(_env_file=None)
    assert s.reasoning_model == "claude-sonnet-5-5"
    assert s.copy_model == "claude-haiku-5-5"


def test_dotenv_file_overrides(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AA_MODEL_REASONING=claude-opus-5-5\nAA_MODEL_COPY=\n")
    s = Settings(_env_file=env)
    assert s.reasoning_model == "claude-opus-5-5"
    assert s.copy_model == "claude-haiku-5-5"  # blank in .env → default


def test_model_fields_do_not_shadow_pydantic_methods():
    # A field named `model_copy` would replace BaseModel.model_copy() with a str.
    assert callable(Settings(_env_file=None).model_copy)


def test_override_is_stripped(monkeypatch):
    monkeypatch.setenv("AA_MODEL_REASONING", "  claude-opus-5-5 ")
    assert Settings(_env_file=None).reasoning_model == "claude-opus-5-5"


def test_get_model_resolves_from_settings_at_call_time(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_model", "claude-opus-5-5")
    monkeypatch.setattr(settings, "copy_model", "claude-sonnet-5")
    assert get_model("reasoning") == "claude-opus-5-5"
    assert get_model("copy") == "claude-sonnet-5"
    monkeypatch.setattr(settings, "reasoning_model", "claude-fable-5-1")
    assert get_model("reasoning") == "claude-fable-5-1"


def test_get_model_blank_setting_falls_back_to_default(monkeypatch):
    # A blank assigned after construction (no validation on assignment) still resolves.
    monkeypatch.setattr(settings, "reasoning_model", "  ")
    assert get_model("reasoning") == "claude-sonnet-5-5"


def test_get_model_unknown_role_raises():
    with pytest.raises(KeyError):
        get_model("vision")


def test_llm_clients_pick_up_the_configured_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(settings, "reasoning_model", "claude-opus-5-5")
    monkeypatch.setattr(settings, "copy_model", "claude-haiku-5-5")
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient

    assert AnthropicLLMClient()._model == "claude-opus-5-5"
    assert AnthropicLLMClient(role="copy")._model == "claude-haiku-5-5"
    assert AnthropicResearcherClient()._model == "claude-opus-5-5"
