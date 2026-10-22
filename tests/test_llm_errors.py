"""Every model-call failure maps to one category with a plain sentence for the user.

Table-tested over constructed SDK exceptions (the typed classes the SDK raises per status,
per the claude-api skill's shared/error-codes.md); no network. The API keeps its status codes
(503 missing key, 429 budget, 502 upstream) and adds `category` next to `detail`.
"""

import json

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.errors import CATEGORIES, CATEGORY_MESSAGES, describe_llm_error
from adaptive_academy.llm.keys import MissingAPIKeyError
from adaptive_academy.llm.types import AgentSDKError, StructuredOutputError
from adaptive_academy.llm.usage import BudgetExceededError, UnpricedModelError
from adaptive_academy.models import Concept, Topic, Track

_REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status(cls, code, message, error_type=None):
    body = None
    if error_type:
        body = {"type": "error", "error": {"type": error_type, "message": message}}
    return cls(message, response=httpx.Response(code, request=_REQ), body=body)


CASES = [
    ("auth", _status(anthropic.AuthenticationError, 401, "invalid x-api-key",
                     "authentication_error")),
    ("auth", MissingAPIKeyError()),
    ("permission", _status(anthropic.PermissionDeniedError, 403, "not allowed",
                           "permission_error")),
    ("rate_limited", _status(anthropic.RateLimitError, 429, "slow down", "rate_limit_error")),
    ("overloaded", _status(anthropic.OverloadedError, 529, "Overloaded", "overloaded_error")),
    ("overloaded", _status(anthropic.InternalServerError, 529, "Overloaded")),
    ("overloaded", _status(anthropic.InternalServerError, 500, "Internal error", "api_error")),
    ("out_of_credits", _status(
        anthropic.BadRequestError, 400,
        "Your credit balance is too low to access the Anthropic API. Please go to Plans & "
        "Billing to upgrade or purchase credits.", "invalid_request_error")),
    ("out_of_credits", _status(anthropic.APIStatusError, 402, "billing problem",
                               "billing_error")),
    ("model_unavailable", _status(anthropic.NotFoundError, 404, "model: claude-retired-9",
                                  "not_found_error")),
    ("network", anthropic.APIConnectionError(request=_REQ)),
    ("network", anthropic.APITimeoutError(request=_REQ)),
    ("refusal", StructuredOutputError("refusal")),
    ("cut_off", StructuredOutputError("max_tokens")),
    ("cut_off", StructuredOutputError("model_context_window_exceeded")),
    ("cut_off", _status(anthropic.BadRequestError, 400,
                        "prompt is too long: 1200000 tokens > 1000000 maximum",
                        "invalid_request_error")),
    ("cut_off", _status(anthropic.APIStatusError, 413, "request too large",
                        "request_too_large")),
    ("invalid_output", StructuredOutputError("no_tool_use")),
    ("invalid_output", json.JSONDecodeError("Expecting value", '{"a": ', 6)),
    ("budget", BudgetExceededError(5.2, 5.0)),
    ("budget", UnpricedModelError("claude-mystery-1", 5.0)),
    ("agent_sdk", AgentSDKError("subscription usage limit reached")),
    ("unknown", _status(anthropic.BadRequestError, 400, "messages: roles must alternate",
                        "invalid_request_error")),
    ("unknown", RuntimeError("something else")),
]


@pytest.mark.parametrize(("category", "exc"), CASES,
                         ids=[f"{c}-{type(e).__name__}" for c, e in CASES])
def test_classifier_maps_each_failure_to_its_category(category, exc):
    assert describe_llm_error(exc).category == category


def test_every_category_is_covered_by_the_table():
    assert {c for c, _ in CASES} == set(CATEGORIES)


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_message_is_plain(category):
    msg = CATEGORY_MESSAGES[category]
    assert msg.endswith(".")
    assert "—" not in msg and "–" not in msg and "!" not in msg
    # Short sentences: no sentence over ~25 words.
    for sentence in msg.split(". "):
        assert len(sentence.split()) <= 25, sentence


def test_status_codes_stay_as_they_were():
    assert describe_llm_error(MissingAPIKeyError()).status_code == 503
    assert describe_llm_error(BudgetExceededError(1, 1)).status_code == 429
    assert describe_llm_error(
        _status(anthropic.RateLimitError, 429, "x", "rate_limit_error")).status_code == 502
    assert describe_llm_error(StructuredOutputError("refusal")).status_code == 502


def test_detail_leads_with_the_plain_sentence_and_adds_the_upstream_message():
    exc = _status(anthropic.BadRequestError, 400,
                  "Your credit balance is too low to access the Anthropic API.",
                  "invalid_request_error")
    detail = describe_llm_error(exc).detail
    assert detail.startswith(CATEGORY_MESSAGES["out_of_credits"])
    assert "credit balance is too low" in detail


def test_upstream_message_is_read_from_the_error_body_not_the_sdk_wrapper():
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": "inner"}}
    exc = anthropic.BadRequestError(f"Error code: 400 - {body}",
                                    response=httpx.Response(400, request=_REQ), body=body)
    detail = describe_llm_error(exc).detail
    assert "inner" in detail and "Error code" not in detail


def test_upstream_text_is_capped():
    exc = _status(anthropic.BadRequestError, 400, "x" * 5000, "invalid_request_error")
    assert len(describe_llm_error(exc).detail) <= 500


def test_auth_detail_names_the_setting_and_does_not_echo_upstream():
    exc = _status(anthropic.AuthenticationError, 401, "invalid x-api-key sk-ant-SECRET",
                  "authentication_error")
    detail = describe_llm_error(exc).detail
    assert "ANTHROPIC_API_KEY" in detail and "SECRET" not in detail


def test_model_unavailable_keeps_naming_the_model_and_setting():
    exc = _status(anthropic.NotFoundError, 404, "model: claude-somewhere-else",
                  "not_found_error")
    detail = describe_llm_error(exc).detail
    assert "'claude-somewhere-else'" in detail and "AA_MODEL_REASONING" in detail


def test_budget_and_missing_key_keep_their_specific_text():
    assert "$5.20 spent today" in describe_llm_error(BudgetExceededError(5.2, 5.0)).detail
    assert "No ANTHROPIC_API_KEY configured" in describe_llm_error(MissingAPIKeyError()).detail


# --- through the API -------------------------------------------------------------------


class _RaisingLLM:
    def __init__(self, exc):
        self._exc = exc

    def complete(self, system, messages, tools):
        raise self._exc


def _assess(session, exc):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: _RaisingLLM(exc)
    try:
        return TestClient(app).post(f"/api/concepts/{concept.id}/assess",
                                    json={"kind": "self_explanation", "response": "..."})
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(("category", "exc", "status"), [
    ("out_of_credits", _status(anthropic.BadRequestError, 400,
                               "Your credit balance is too low.", "invalid_request_error"), 502),
    ("overloaded", _status(anthropic.OverloadedError, 529, "Overloaded", "overloaded_error"),
     502),
    ("network", anthropic.APIConnectionError(request=_REQ), 502),
    ("agent_sdk", AgentSDKError("subscription usage limit reached"), 502),
    ("invalid_output", json.JSONDecodeError("Expecting value", "{", 1), 502),
    ("cut_off", StructuredOutputError("max_tokens"), 502),
    ("budget", BudgetExceededError(5.2, 5.0), 429),
    ("auth", MissingAPIKeyError(), 503),
])
def test_api_error_json_carries_category_and_detail(session, category, exc, status):
    r = _assess(session, exc)
    assert r.status_code == status
    body = r.json()
    assert body["category"] == category
    assert body["detail"]
