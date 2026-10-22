"""Which service the model calls go to (AA_LLM_BACKEND), and how to reach it.

Three backends:
- `anthropic` (the default): the Anthropic API with ANTHROPIC_API_KEY.
- `openrouter`: OpenRouter's Anthropic-format Messages endpoint with OPENROUTER_API_KEY. The
  same Anthropic SDK clients are used, pointed at OpenRouter's base URL (the SDK appends
  /v1/messages) and sending the key as `Authorization: Bearer`.
- `agent_sdk`: a Claude subscription through the Claude Agent SDK (api/deps.py builds other
  clients for it). Its API-key bridge (tool turns) stays on the Anthropic backend.

Read from the environment at call time, like the rest of the LLM config, so a restarted API
picks up .env and tests can monkeypatch it. Differences between models (not services) live in
llm/model_catalog.py.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from adaptive_academy.settings import DEFAULT_MODEL_COPY, DEFAULT_MODEL_REASONING

BACKEND_ANTHROPIC = "anthropic"
BACKEND_AGENT_SDK = "agent_sdk"
BACKEND_OPENROUTER = "openrouter"
BACKENDS = (BACKEND_ANTHROPIC, BACKEND_AGENT_SDK, BACKEND_OPENROUTER)

# Backends whose calls are paid for by an API key, so they count toward AA_DAILY_BUDGET_USD.
# Agent SDK calls are billed to the Claude subscription.
KEY_BILLED_BACKENDS = (BACKEND_ANTHROPIC, BACKEND_OPENROUTER)

OPENROUTER_BASE_URL = "https://openrouter.ai/api"

# OpenRouter provider routing, sent on every request (as `provider` in the body). With
# `data_collection: "deny"`, OpenRouter uses "only providers which do not collect user data"
# (it is "allow" by default, which includes providers that store prompts and may train on
# them). Field and values confirmed in OpenRouter's Messages API reference (ProviderPreferences)
# and its provider-selection guide, read 2026-10-22.
OPENROUTER_PROVIDER_PREFERENCES: Mapping[str, Any] = MappingProxyType(
    {"data_collection": "deny"})


@dataclass(frozen=True)
class Backend:
    name: str
    # The service named to people: "Anthropic" or "OpenRouter".
    provider: str
    # The environment variable holding the key.
    key_env: str
    # None: the SDK's default (api.anthropic.com, or ANTHROPIC_BASE_URL when set).
    base_url: str | None
    # True: send the key as `Authorization: Bearer` (the SDK's auth_token). False: x-api-key.
    bearer_auth: bool
    # role → model id, used when AA_MODEL_REASONING / AA_MODEL_COPY is blank.
    default_models: Mapping[str, str]
    # Extra request-body fields sent on every Messages call (the SDK's extra_body).
    extra_body: Mapping[str, Any] | None
    # True when each response's usage reports what the service charged (usage.cost).
    reports_cost: bool
    # Where to add credits, for error messages.
    billing_page: str
    # Placeholder values that are not a key (the .env.example value and documented examples).
    placeholder_keys: frozenset[str] = field(default_factory=frozenset)


ANTHROPIC = Backend(
    name=BACKEND_ANTHROPIC,
    provider="Anthropic",
    key_env="ANTHROPIC_API_KEY",
    base_url=None,
    bearer_auth=False,
    default_models=MappingProxyType(
        {"reasoning": DEFAULT_MODEL_REASONING, "copy": DEFAULT_MODEL_COPY}),
    extra_body=None,
    reports_cost=False,
    billing_page="the Anthropic Console",
    placeholder_keys=frozenset({"sk-ant-xxxxx", "sk-ant-...", "sk-ant-…"}),
)

OPENROUTER = Backend(
    name=BACKEND_OPENROUTER,
    provider="OpenRouter",
    key_env="OPENROUTER_API_KEY",
    base_url=OPENROUTER_BASE_URL,
    bearer_auth=True,
    # OpenRouter model slugs: vendor/model, with dots in the version.
    default_models=MappingProxyType(
        {"reasoning": "anthropic/claude-sonnet-5.5", "copy": "anthropic/claude-haiku-5.5"}),
    extra_body=MappingProxyType({"provider": OPENROUTER_PROVIDER_PREFERENCES}),
    reports_cost=True,
    billing_page="your OpenRouter account (openrouter.ai/settings/credits)",
    placeholder_keys=frozenset({"sk-or-xxxxx", "sk-or-...", "sk-or-…", "sk-or-v1-xxxxx"}),
)


def current_backend_name() -> str:
    """The configured backend: AA_LLM_BACKEND, case and spaces ignored; anything else is
    the default (anthropic)."""
    raw = os.getenv("AA_LLM_BACKEND", "").strip().lower()
    return raw if raw in BACKENDS else BACKEND_ANTHROPIC


def use_agent_sdk() -> bool:
    return current_backend_name() == BACKEND_AGENT_SDK


def api_backend() -> Backend:
    """The backend the API-key (Anthropic SDK) clients use: OpenRouter when selected, else
    Anthropic (also under agent_sdk, whose bridge needs the Anthropic key)."""
    return OPENROUTER if current_backend_name() == BACKEND_OPENROUTER else ANTHROPIC


def request_extra_body(backend: Backend) -> dict[str, Any]:
    """Keyword arguments for `messages.create` carrying the backend's extra body fields."""
    if not backend.extra_body:
        return {}
    return {"extra_body": _plain(backend.extra_body)}


def _plain(value: Any) -> Any:
    # MappingProxyType → dict, so the SDK serialises it and callers can't mutate the constant.
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    return value
