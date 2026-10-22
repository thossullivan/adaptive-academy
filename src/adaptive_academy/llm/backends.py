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

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from adaptive_academy.settings import DEFAULT_MODEL_COPY, DEFAULT_MODEL_REASONING

BACKEND_ANTHROPIC = "anthropic"
BACKEND_AGENT_SDK = "agent_sdk"
BACKEND_OPENROUTER = "openrouter"
BACKENDS = (BACKEND_ANTHROPIC, BACKEND_AGENT_SDK, BACKEND_OPENROUTER)

# Backends whose calls are paid for by an API key, so they count toward AA_DAILY_BUDGET_USD.
# Agent SDK calls are billed to the Claude subscription.
KEY_BILLED_BACKENDS = (BACKEND_ANTHROPIC, BACKEND_OPENROUTER)

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api"
OPENROUTER_HOST = "openrouter.ai"

# OpenRouter provider routing, sent on every request (as `provider` in the body). The default,
# `data_collection: "allow"`, includes "providers which store user data non-transiently and may
# train on it"; "deny" excludes them. It does NOT mean no retention: a provider may still keep
# prompts for a while (Anthropic keeps them for trust and safety review). Zero data retention
# is a separate, stricter preference, `zdr: true`, which may leave fewer (or no) providers for
# a model; it is not sent. Fields and values from OpenRouter's Messages API reference
# (ProviderPreferences) and its provider-selection guide, read 2026-10-22.
OPENROUTER_PROVIDER_PREFERENCES: Mapping[str, Any] = MappingProxyType(
    {"data_collection": "deny"})


@dataclass(frozen=True)
class Backend:
    name: str
    # The service named to people: "Anthropic" or "OpenRouter".
    provider: str
    # The environment variable holding the key.
    key_env: str
    # None: the Anthropic endpoint, `anthropic_base_url()` (api.anthropic.com, or a proxy set
    # in ANTHROPIC_BASE_URL that isn't OpenRouter).
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
    # Key prefixes of the OTHER service: a key starting with one is in the wrong variable.
    foreign_key_prefixes: tuple[tuple[str, str], ...] = ()  # (prefix, that service's name)


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
    foreign_key_prefixes=(("sk-or-", "OpenRouter"),),
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
    foreign_key_prefixes=(("sk-ant-", "Anthropic"),),
)


def current_backend_name() -> str:
    """The configured backend: AA_LLM_BACKEND, case and spaces ignored; anything else is
    the default (anthropic), and `backend_setting_problem()` says so."""
    raw = os.getenv("AA_LLM_BACKEND", "").strip().lower()
    return raw if raw in BACKENDS else BACKEND_ANTHROPIC


def backend_setting_problem() -> str | None:
    """A plain warning when AA_LLM_BACKEND holds a value that isn't a backend (it then falls
    back to the Anthropic API), else None."""
    raw = os.getenv("AA_LLM_BACKEND", "").strip()
    if not raw or raw.lower() in BACKENDS:
        return None
    return (f"AA_LLM_BACKEND is set to '{raw[:40]}', which is not a backend this app knows, so "
            "it is using the Anthropic API. Use anthropic, openrouter, or agent_sdk (or leave "
            "it unset), then restart the API.")


def use_agent_sdk() -> bool:
    return current_backend_name() == BACKEND_AGENT_SDK


def in_container() -> bool:
    """True inside the Docker image (its Dockerfile sets AA_IN_CONTAINER=1)."""
    return os.getenv("AA_IN_CONTAINER", "").strip() == "1"


AGENT_SDK_IN_CONTAINER_DETAIL = (
    "AA_LLM_BACKEND=agent_sdk needs Claude Code signed in on the host, and this container "
    "doesn't have it, so no model calls can run. Unset AA_LLM_BACKEND to use "
    "ANTHROPIC_API_KEY, or set it to openrouter with OPENROUTER_API_KEY, then restart the "
    "container (`just up`). Or run the app on the host with `just api`."
)


def agent_sdk_unavailable() -> bool:
    """agent_sdk is selected but can't run here (the container has no Claude Code). Calls are
    refused with AGENT_SDK_IN_CONTAINER_DETAIL rather than quietly billed to an API key."""
    return use_agent_sdk() and in_container()


def _is_openrouter_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host == OPENROUTER_HOST or host.endswith("." + OPENROUTER_HOST)


def anthropic_base_url() -> str:
    """The Anthropic backend's endpoint: ANTHROPIC_BASE_URL when it points at a proxy or
    gateway, else api.anthropic.com. Never openrouter.ai: OpenRouter's own Claude Code setup
    exports ANTHROPIC_BASE_URL=https://openrouter.ai/api, and following it would send the
    Anthropic key there (use AA_LLM_BACKEND=openrouter for OpenRouter)."""
    url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
    if not url:
        return ANTHROPIC_API_URL
    if _is_openrouter_url(url):
        logger.warning("ANTHROPIC_BASE_URL points at OpenRouter; the Anthropic backend ignores "
                       "it and calls %s. Set AA_LLM_BACKEND=openrouter to use OpenRouter.",
                       ANTHROPIC_API_URL)
        return ANTHROPIC_API_URL
    return url


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
