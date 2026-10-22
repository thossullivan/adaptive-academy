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
"""

import json
import re
from dataclasses import dataclass

import anthropic

from adaptive_academy.llm.keys import MissingAPIKeyError
from adaptive_academy.llm.registry import MODEL_ENV_VARS, ROLES, get_model
from adaptive_academy.llm.types import AgentSDKError, StructuredOutputError
from adaptive_academy.llm.usage import BudgetExceededError

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

# Upstream text is not ours; cap how much of it is echoed back.
_UPSTREAM_MAX = 300


@dataclass(frozen=True)
class LLMFailure:
    category: str
    detail: str
    status_code: int


# Upstream says e.g. "model: claude-foo-1". Only an id-shaped token is lifted, so nothing
# else from the upstream text (which we don't control) is echoed back.
_MODEL_IN_MESSAGE = re.compile(r"\bmodel:\s*([A-Za-z0-9][A-Za-z0-9._:@/-]{0,99})")


def model_unavailable_detail(exc: anthropic.APIStatusError) -> str:
    """A legible fix for a model the API doesn't recognise: name the id and the setting."""
    match = _MODEL_IN_MESSAGE.search(getattr(exc, "message", "") or str(exc))
    model = match.group(1).rstrip(".,;:'\"") if match else None
    env_vars = [MODEL_ENV_VARS[role] for role in ROLES if model and get_model(role) == model]
    if not env_vars:
        env_vars = [MODEL_ENV_VARS[role] for role in ROLES]
    setting = env_vars[0] if len(env_vars) == 1 else f"{env_vars[0]} (or {', '.join(env_vars[1:])})"
    subject = f"The model '{model}'" if model else "The configured model"
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


def _with_upstream(category: str, upstream: str, source: str = "Anthropic") -> str:
    sentence = CATEGORY_MESSAGES[category]
    if not upstream:
        return sentence
    return f"{sentence} {source} said: {upstream[:_UPSTREAM_MAX]}"


def _status_category(exc: anthropic.APIStatusError) -> str:
    status = exc.status_code
    kind = getattr(exc, "type", None)
    text = _upstream_message(exc).lower()
    if status == 401:
        return "auth"
    if status == 402 or kind == "billing_error" or "credit balance" in text:
        return "out_of_credits"
    if status == 403:
        return "permission"
    if status == 404:
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
    category = classify_llm_error(exc)
    if isinstance(exc, MissingAPIKeyError):
        # Our own message, already says exactly how to set the key.
        return LLMFailure(category, str(exc), 503)
    if isinstance(exc, BudgetExceededError):
        # Our own message: what was spent, the limit, and how to raise it.
        return LLMFailure(category, str(exc), 429)
    if isinstance(exc, StructuredOutputError):
        # Reason-specific plain text (types.py), more precise than the category sentence.
        return LLMFailure(category, exc.detail, 502)
    if category == "model_unavailable":
        return LLMFailure(category, model_unavailable_detail(exc), 502)
    if category == "agent_sdk":
        return LLMFailure(category, _with_upstream(category, str(exc).strip(), "The SDK"), 502)
    if category in ("auth", "network", "invalid_output", "rate_limited"):
        # The sentence says it all; the upstream text adds nothing a user can act on.
        return LLMFailure(category, CATEGORY_MESSAGES[category], 502)
    return LLMFailure(category, _with_upstream(category, _upstream_message(exc)), 502)
