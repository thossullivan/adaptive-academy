"""Model ids are configurable (AA_MODEL_REASONING / AA_MODEL_COPY), resolved at call time."""

import pytest

from adaptive_academy.llm.registry import get_model
from adaptive_academy.settings import Settings, settings


@pytest.fixture(autouse=True)
def _no_model_env(monkeypatch):
    monkeypatch.delenv("AA_MODEL_REASONING", raising=False)
    monkeypatch.delenv("AA_MODEL_COPY", raising=False)


# Unset settings stay blank: blank means "the backend's default" (llm/backends.py), which
# get_model resolves, because the Anthropic and OpenRouter backends name the same model
# differently.
UNSET = ""


def test_defaults_are_the_current_claude_5_family(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    s = Settings(_env_file=None)
    assert (s.reasoning_model, s.copy_model) == (UNSET, UNSET)
    monkeypatch.setattr(settings, "reasoning_model", s.reasoning_model)
    monkeypatch.setattr(settings, "copy_model", s.copy_model)
    assert get_model("reasoning") == "claude-sonnet-5-5"
    assert get_model("copy") == "claude-haiku-5-5"


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
    assert s.reasoning_model == UNSET
    assert s.copy_model == UNSET


def test_dotenv_file_overrides(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AA_MODEL_REASONING=claude-opus-5-5\nAA_MODEL_COPY=\n")
    s = Settings(_env_file=env)
    assert s.reasoning_model == "claude-opus-5-5"
    assert s.copy_model == UNSET  # blank in .env → default


@pytest.mark.parametrize("name", ["REASONING_MODEL", "reasoning_model"])
def test_unprefixed_reasoning_env_name_is_ignored(monkeypatch, name):
    # Only AA_MODEL_REASONING configures the model; a stray REASONING_MODEL in the shell
    # must not silently win over .env.
    monkeypatch.setenv(name, "claude-opus-5-5")
    assert Settings(_env_file=None).reasoning_model == UNSET


@pytest.mark.parametrize("name", ["COPY_MODEL", "copy_model"])
def test_unprefixed_copy_env_name_is_ignored(monkeypatch, name):
    monkeypatch.setenv(name, "claude-opus-5-5")
    assert Settings(_env_file=None).copy_model == UNSET


def test_unprefixed_name_in_dotenv_is_ignored(tmp_path):
    env = tmp_path / ".env"
    env.write_text("REASONING_MODEL=claude-opus-5-5\nCOPY_MODEL=claude-opus-5-5\n"
                   "AA_REASONING_MODEL=claude-opus-5-5\n")
    s = Settings(_env_file=env)
    assert s.reasoning_model == UNSET
    assert s.copy_model == UNSET


def test_prefixed_env_beats_unprefixed(monkeypatch, tmp_path):
    monkeypatch.setenv("REASONING_MODEL", "claude-haiku-4-5")
    env = tmp_path / ".env"
    env.write_text("AA_MODEL_REASONING=claude-opus-5-5\n")
    assert Settings(_env_file=env).reasoning_model == "claude-opus-5-5"


def test_fields_can_still_be_set_by_name_in_code():
    s = Settings(_env_file=None, reasoning_model="claude-opus-5-5", copy_model="claude-sonnet-5-5")
    assert s.reasoning_model == "claude-opus-5-5"
    assert s.copy_model == "claude-sonnet-5-5"


# --- AA_DAILY_BUDGET_USD ----------------------------------------------------------------


@pytest.fixture
def _no_budget_env(monkeypatch):
    monkeypatch.delenv("AA_DAILY_BUDGET_USD", raising=False)


@pytest.mark.usefixtures("_no_budget_env")
@pytest.mark.parametrize(("raw", "expected"), [
    ("", None), ("  ", None), ("5", 5.0), ("0.25", 0.25), ("0", 0.0),
])
def test_budget_accepts_blank_zero_and_positive(monkeypatch, raw, expected):
    monkeypatch.setenv("AA_DAILY_BUDGET_USD", raw)
    assert Settings(_env_file=None).daily_budget_usd == expected


@pytest.mark.usefixtures("_no_budget_env")
@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "Infinity", "-1", "-0.01"])
def test_budget_rejects_non_finite_and_negative(monkeypatch, raw):
    from pydantic import ValidationError

    monkeypatch.setenv("AA_DAILY_BUDGET_USD", raw)
    with pytest.raises(ValidationError, match="AA_DAILY_BUDGET_USD"):
        Settings(_env_file=None)


@pytest.mark.usefixtures("_no_budget_env")
def test_budget_rejected_in_dotenv_too(tmp_path):
    from pydantic import ValidationError

    env = tmp_path / ".env"
    env.write_text("AA_DAILY_BUDGET_USD=nan\n")
    with pytest.raises(ValidationError, match="AA_DAILY_BUDGET_USD"):
        Settings(_env_file=env)


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
