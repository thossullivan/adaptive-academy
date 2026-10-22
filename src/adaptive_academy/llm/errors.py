"""Classify a failed model call into one category, with a plain sentence for the user.

The API layer (api/app.py) turns any failure from an LLM-backed route into JSON with `detail`
(what happened and what to do, plus the upstream message where it helps) and `category` (a
stable key the UI can branch on). Status codes are unchanged: 503 for a missing key, 429 for
the daily spending limit, 502 for everything that failed upstream.

Anthropic failures are classified by the SDK's typed exceptions and status codes (claude-api
skill, shared/error-codes.md): 401 auth, 402 billing, 403 permission, 404 model not found, 413
too large, 429 rate limit, 5xx/529 server trouble, APIConnectionError (and its subclass
APITimeoutError) for the network. The SDK sends "credit balance is too low" as a 400, so that
one is matched on its message.

OpenRouter (AA_LLM_BACKEND=openrouter) reaches us through the same SDK, so the same exception
types arrive, and its errors map into the same categories: 402 (insufficient credits, also
`payment_required` / `billing_error`) is out_of_credits, 429 is rate_limited, an unknown model
slug is model_unavailable, and so is a 503 "no available model provider that meets your
routing requirements" (OpenRouter docs, api_reference/errors-and-debugging): with the privacy
preference in llm/backends.py, that means no provider for the model promises not to store
prompts. The plain messages name the service in use and its key.
"""

import json
import re
from dataclasses import dataclass

import anthropic

from adaptive_academy.llm.backends import BACKEND_OPENROUTER, Backend, api_backend
from adaptive_academy.llm.keys import MissingAPIKeyError
from adaptive_academy.llm.registry import MODEL_ENV_VARS, ROLES, get_model
from adaptive_academy.llm.types import AgentSDKError, StructuredOutputError
from adaptive_academy.llm.usage import BudgetExceededError

# The Anthropic backend's wording (the default).
CATEGORY_MESSAGES = {
    "auth": "Anthropic did not accept the API key. Check ANTHROPIC_API_KEY in .env, then "
            "restart the API.",
    "permission": "This API key is not allowed to make that request. Check the key's "
                  "organization and workspace in the Anthropic Console.",
    "rate_limited": "Anthropic is limiting how fast this API key can make requests. Wait a "
                    "minute, then try again.",
    "overloaded": "Anthropic's service is overloaded or having trouble right now. Wait a few "
                  "minutes, then try again.",
    "out_of_credits": "Your Anthropic account is out of credits. Add credits in the Anthropic "
                      "Console, then try again.",
    "model_unavailable": "The configured model is not available to this API key. Set "
                         "AA_MODEL_REASONING or AA_MODEL_COPY in .env to a current model, then "
                         "restart the API.",
    "network": "Could not reach Anthropic. Check your internet connection, then try again.",
    "refusal": "The model declined to answer this request. Rephrase the input, then try "
               "again.",
    "cut_off": "The request or the model's answer was too long, so the answer was cut off. "
               "Try again with less input or a narrower request.",
    "invalid_output": "The model's answer was not in the expected format. Try again. It "
                      "usually works the second time.",
    "budget": "You reached the daily spending limit set in AA_DAILY_BUDGET_USD. Raise or "
              "unset it in .env and restart the API, or wait until tomorrow.",
    "agent_sdk": "The Claude subscription backend (Agent SDK) failed. Check that Claude Code "
                 "is signed in to your plan, then try again.",
    "unknown": "The model call failed for an unexpected reason. Try again, and check the API "
               "log if it keeps happening.",
}
CATEGORIES = tuple(CATEGORY_MESSAGES)

# The OpenRouter backend's wording, where it differs.
_OPENROUTER_MESSAGES = {
    "auth": "OpenRouter did not accept the API key. Check OPENROUTER_API_KEY in .env, then "
            "restart the API.",
    "permission": "OpenRouter refused this request. A guardrail, a moderation check, or the "
                  "key's settings blocked it. Check the key's settings on OpenRouter.",
    "rate_limited": "OpenRouter is limiting how fast this API key can make requests. Wait a "
                    "minute, then try again.",
    "overloaded": "OpenRouter or the model's provider is overloaded or having trouble right "
                  "now. Wait a few minutes, then try again.",
    "out_of_credits": "Your OpenRouter account is out of credits. Add credits on OpenRouter, "
                      "then try again.",
    "model_unavailable": "The configured model is not available on OpenRouter. Set "
                         "AA_MODEL_REASONING or AA_MODEL_COPY in .env to an OpenRouter model "
                         "id, then restart the API.",
    "network": "Could not reach OpenRouter. Check your internet connection, then try again.",
}


def category_messages(backend: Backend) -> dict[str, str]:
    """Every category's plain sentence, worded for this backend."""
    if backend.name == BACKEND_OPENROUTER:
        return {**CATEGORY_MESSAGES, **_OPENROUTER_MESSAGES}
    return dict(CATEGORY_MESSAGES)


# Upstream text is not ours; cap how much of it is echoed back.
_UPSTREAM_MAX = 300


@dataclass(frozen=True)
class LLMFailure:
    category: str
    detail: str
    status_code: int


# Upstream names a model in a few shapes: Anthropic's "model: claude-foo-1", OpenRouter's
# "x/y is not a valid model ID" and "No endpoints found for x/y.". Only an id-shaped token is
# lifted, so nothing else from the upstream text (which we don't control) is echoed back.
_MODEL_ID = r"([A-Za-z0-9][A-Za-z0-9._:@/-]{0,99})"
_MODEL_IN_MESSAGE = (
    re.compile(r"\bmodel:\s*" + _MODEL_ID),
    re.compile(_MODEL_ID + r" is not a valid model id", re.IGNORECASE),
    re.compile(r"no endpoints found for " + _MODEL_ID, re.IGNORECASE),
)
# OpenRouter: an unknown slug, and no provider meeting the routing (privacy) requirements.
_UNKNOWN_MODEL_TEXT = ("is not a valid model id", "no endpoints found for")
_NO_PROVIDER_TEXT = ("routing requirements", "data policy")


def _model_in(text: str) -> str | None:
    for pattern in _MODEL_IN_MESSAGE:
        match = pattern.search(text)
        if match:
            return match.group(1).rstrip(".,;:'\"")
    return None


def _setting_for(model: str | None) -> str:
    env_vars = [MODEL_ENV_VARS[role] for role in ROLES if model and get_model(role) == model]
    if not env_vars:
        env_vars = [MODEL_ENV_VARS[role] for role in ROLES]
    return env_vars[0] if len(env_vars) == 1 else f"{env_vars[0]} (or {', '.join(env_vars[1:])})"


def model_unavailable_detail(exc: anthropic.APIStatusError, backend: Backend | None = None) -> str:
    """A legible fix for a model the service doesn't offer: name the id and the setting."""
    backend = backend or api_backend()
    text = getattr(exc, "message", "") or str(exc)
    upstream = _upstream_message(exc)
    model = _model_in(upstream) or _model_in(text)
    setting = _setting_for(model)
    if any(s in upstream.lower() for s in _NO_PROVIDER_TEXT):
        return ("No provider on OpenRouter can serve this model while promising not to store "
                "your prompts, which this app requires. "
                f"Set {setting} in .env to another model and restart the API.")
    subject = f"The model '{model}'" if model else "The configured model"
    if backend.name == BACKEND_OPENROUTER:
        return (f"{subject} is not available on OpenRouter. Set {setting} in .env to an "
                "OpenRouter model id (for example anthropic/claude-sonnet-5.5) and restart "
                "the API.")
    return (f"{subject} is not available to this API key. "
            f"Set {setting} in .env to a current model and restart the API.")


def _upstream_message(exc: BaseException) -> str:
    """The API's own error message: `error.message` from the body when there is one (the SDK
    wraps it as "Error code: 400 - {...}"), else the exception's message."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        inner = body["error"].get("message")
        if isinstance(inner, str) and inner.strip():
            return inner.strip()
    return (getattr(exc, "message", None) or str(exc)).strip()


def _error_type(exc: anthropic.APIStatusError) -> str | None:
    """`error.type` from the body (the SDK reads it into exc.type for Anthropic's shape)."""
    kind = getattr(exc, "type", None)
    if kind:
        return kind
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        inner = body["error"].get("type")
        return inner if isinstance(inner, str) else None
    return None


def _with_upstream(sentence: str, upstream: str, source: str) -> str:
    if not upstream:
        return sentence
    return f"{sentence} {source} said: {upstream[:_UPSTREAM_MAX]}"


def _status_category(exc: anthropic.APIStatusError) -> str:
    status = exc.status_code
    kind = _error_type(exc)
    text = _upstream_message(exc).lower()
    if status == 401:
        return "auth"
    if (status == 402 or kind in ("billing_error", "payment_required")
            or "credit balance" in text):
        return "out_of_credits"
    if status == 403:
        return "permission"
    if status == 404 or any(s in text for s in _UNKNOWN_MODEL_TEXT + _NO_PROVIDER_TEXT):
        return "model_unavailable"
    if status == 429:
        return "rate_limited"
    if status == 413 or "prompt is too long" in text or "context window" in text:
        return "cut_off"
    if status >= 500 or kind in ("overloaded_error", "api_error"):
        return "overloaded"
    return "unknown"


def classify_llm_error(exc: BaseException) -> str:
    """The category key for any failure raised by (or around) a model call."""
    if isinstance(exc, MissingAPIKeyError):
        return "auth"
    if isinstance(exc, BudgetExceededError):
        return "budget"
    if isinstance(exc, StructuredOutputError):
        if exc.reason == "refusal":
            return "refusal"
        if exc.reason in ("max_tokens", "model_context_window_exceeded"):
            return "cut_off"
        return "invalid_output"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_output"
    if isinstance(exc, AgentSDKError):
        return "agent_sdk"
    if isinstance(exc, anthropic.APIConnectionError):  # APITimeoutError included
        return "network"
    if isinstance(exc, anthropic.APIStatusError):
        return _status_category(exc)
    return "unknown"


def describe_llm_error(exc: BaseException) -> LLMFailure:
    """Category, the `detail` text for the API response, and its HTTP status."""
    backend = api_backend()
    messages = category_messages(backend)
    category = classify_llm_error(exc)
    if isinstance(exc, MissingAPIKeyError):
        # Our own message, already says exactly which key to set and how.
        return LLMFailure(category, str(exc), 503)
    if isinstance(exc, BudgetExceededError):
        # Our own message: what was spent, the limit, and how to raise it.
        return LLMFailure(category, str(exc), 429)
    if isinstance(exc, StructuredOutputError):
        # Reason-specific plain text (types.py), more precise than the category sentence.
        return LLMFailure(category, exc.detail, 502)
    if category == "model_unavailable":
        return LLMFailure(category, model_unavailable_detail(exc, backend), 502)
    if category == "agent_sdk":
        return LLMFailure(category, _with_upstream(messages[category], str(exc).strip(),
                                                   "The SDK"), 502)
    if category in ("auth", "network", "invalid_output", "rate_limited"):
        # The sentence says it all; the upstream text adds nothing a user can act on.
        return LLMFailure(category, messages[category], 502)
    return LLMFailure(category, _with_upstream(messages[category], _upstream_message(exc),
                                               backend.provider), 502)
