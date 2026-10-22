"""Record REAL Anthropic API responses into tests/fixtures/anthropic_responses/ (manual tool).

The replay tests (tests/test_response_replay.py) serve those fixture files to the real SDK
through an httpx MockTransport. The checked-in fixtures are built from the shapes documented
in the claude-api skill (`"_source": "documented"`). This script refreshes them from the live
API (`"_source": "recorded"`), so a change in what the API actually sends shows up as a
reviewed fixture diff and a failing replay test instead of a production surprise.

It SPENDS MONEY on your ANTHROPIC_API_KEY, so it refuses to run without `--live`. Every run,
live or not, first prints the plan and a cost estimate; a live run then asks for
confirmation (skip with `--yes`).

    uv run python scripts/record_response_fixtures.py               # plan + estimate only
    uv run python scripts/record_response_fixtures.py --live        # record everything
    uv run python scripts/record_response_fixtures.py --live --only tutor_reply json_strict

Options: `--only SCENARIO ...` records a subset; `--model ID` overrides the reasoning model
(default: AA_MODEL_REASONING, else the app default); `--out DIR` writes elsewhere.

How it records: the scenarios drive the app's own clients (AnthropicLLMClient,
AnthropicResearcherClient) through their `http_client=` seam, with an httpx response hook
that captures each raw HTTP body before the SDK parses it. So the requests are the app's
real requests and the fixtures are exactly what came over the wire. Usage rows are NOT
written to the app database (recording is switched off for the run); the script prints the
cost each response reports instead.

A scenario's fixture is written only when the live response has the shape the scenario is
for (e.g. a pause_turn for research_pause_turn); otherwise it prints why and keeps the
existing file. Model behaviour can't be forced, so rerun or keep the documented fixture.

Redaction: message, tool-use and server-tool-use ids are replaced by stable placeholders
(references such as tool_use_id stay consistent), and thinking signatures, encrypted search
content and indexes, and request ids by placeholders. None of those matter to the replay:
they are opaque strings our code passes through unchanged. Everything else is kept verbatim.

Not recordable on demand, so they stay documented-only: json_refusal (a safety classifier
decline), json_context_window_exceeded (needs a ~1M-token prompt), error_400_credit_balance
(an empty account), error_429_rate_limit and error_529_overloaded (server conditions).
error_401_authentication (a deliberately bad key) and error_404_model_not_found (a model id
that does not exist) cost nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import anthropic
import httpx

from adaptive_academy.engine.tools import TOOLS
from adaptive_academy.llm import pricing, registry, usage
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.anthropic_researcher import (
    MAX_PAUSE_CONTINUATIONS,
    AnthropicResearcherClient,
)
from adaptive_academy.llm.backends import BACKEND_ANTHROPIC, current_backend_name
from adaptive_academy.llm.keys import require_anthropic_api_key
from adaptive_academy.llm.researcher_types import SearchBrief
from adaptive_academy.llm.types import StructuredOutputError

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "anthropic_responses"
MISSING_MODEL = "claude-sonnet-3-9"  # must stay an id that does not exist (404 scenario)

TUTOR_SYSTEM = (
    "You are a Socratic tutor for gradient descent. Call log_attempt as soon as the learner "
    "makes a genuine attempt. Call reveal_solution only after an attempt is logged and the "
    "learner asks for the answer."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "verdict": {"type": "string"},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "verdict", "gaps"],
}
GRADE_SYSTEM = "Grade the learner's explanation of why a too-large learning rate diverges."
GRADE_USER = {"role": "user", "content": "Learner: a big step overshoots the minimum, so "
                                         "the loss bounces and grows."}


# --- capture and redaction -----------------------------------------------------------------


@dataclass
class Captured:
    status: int
    headers: dict[str, str]
    body: Any


class Recorder:
    """An httpx client whose response hook keeps every raw response body."""

    def __init__(self) -> None:
        self.responses: list[Captured] = []
        self.client = httpx.Client(timeout=600, event_hooks={"response": [self._hook]})

    def _hook(self, response: httpx.Response) -> None:
        response.read()
        try:
            body = response.json()
        except ValueError:
            body = {"_unparseable": response.text}
        kept = {k: v for k, v in response.headers.items() if k.lower() == "retry-after"}
        self.responses.append(Captured(response.status_code, kept, body))


_ID_KEYS = ("id", "tool_use_id")
_OPAQUE_KEYS = {"signature": "signature", "encrypted_content": "encrypted-content",
                "encrypted_index": "encrypted-index"}


class Redactor:
    """Stable placeholders for ids (shared across one run, so references still match)."""

    def __init__(self) -> None:
        self.ids: dict[str, str] = {}
        self.counts: dict[str, int] = {}

    def _next(self, kind: str) -> int:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return self.counts[kind]

    def _id(self, value: str) -> str:
        if value not in self.ids:
            prefix = value.split("_", 1)[0] if "_" in value else "id"
            self.ids[value] = f"{prefix}_recorded{self._next(prefix):04d}"
        return self.ids[value]

    def __call__(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self(v) for v in value]
        if not isinstance(value, dict):
            return value
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _ID_KEYS and isinstance(item, str):
                out[key] = self._id(item)
            elif key in _OPAQUE_KEYS and isinstance(item, str) and item:
                kind = _OPAQUE_KEYS[key]
                out[key] = f"recorded-{kind}-redacted-{self._next(kind):04d}"
            elif key == "request_id" and isinstance(item, str):
                out[key] = "req_recorded_redacted"
            else:
                out[key] = self(item)
        return out


# --- scenarios -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    name: str
    fixtures: tuple[str, ...]
    run: Callable[[Recorder], list[str | None]]
    # Rough sizing for the estimate: calls, input tokens per call, typical output tokens per
    # call, the max_tokens cap per call, and web searches at most.
    calls: int
    input_tokens: int
    typical_output: int
    max_output: int
    max_searches: int = 0


def _stop(captured: Captured) -> str | None:
    return captured.body.get("stop_reason") if isinstance(captured.body, dict) else None


def _types(captured: Captured) -> list[str]:
    return [b.get("type") for b in captured.body.get("content", [])]


def _tutor_reply(rec: Recorder) -> list[str | None]:
    llm = AnthropicLLMClient(http_client=rec.client)
    llm.complete(TUTOR_SYSTEM, [{"role": "user", "content":
                 "Why might gradient descent diverge? Don't tell me, give me a hint."}], TOOLS)
    got = rec.responses[-1]
    if _stop(got) != "end_turn" or "text" not in _types(got):
        return [f"expected end_turn with text, got {_stop(got)} {_types(got)}"]
    if "thinking" not in _types(got):
        return ["no thinking block this time (adaptive thinking skipped a short turn)"]
    return [None]


def _tutor_tools(rec: Recorder) -> list[str | None]:
    llm = AnthropicLLMClient(http_client=rec.client)
    user = {"role": "user", "content": "My attempt: a large learning rate overshoots the "
                                       "minimum, so the loss grows. Now please show me the "
                                       "full worked solution."}
    turn = llm.complete(TUTOR_SYSTEM, [user], TOOLS)
    first = rec.responses[-1]
    if _stop(first) != "tool_use" or not turn.tool_calls:
        return [f"expected a tool_use turn, got {_stop(first)} {_types(first)}", "skipped"]
    results = [{"type": "tool_result", "tool_use_id": c.id, "content": "ok"}
               for c in turn.tool_calls]
    llm.complete(TUTOR_SYSTEM, [user, {"role": "assistant", "content": turn.raw_content},
                                {"role": "user", "content": results}], TOOLS)
    second = rec.responses[-1]
    ok_second = None if _stop(second) == "end_turn" else f"follow-up stopped {_stop(second)}"
    return [None, ok_second]


def _json_strict(rec: Recorder) -> list[str | None]:
    llm = AnthropicLLMClient(http_client=rec.client)
    try:
        llm.complete_json(GRADE_SYSTEM, [GRADE_USER], schema=SCHEMA, tool_name="emit_grade")
    except StructuredOutputError as exc:
        return [f"no tool call ({exc.reason})"]
    got = rec.responses[-1]
    return [None if _stop(got) == "tool_use" else f"stopped {_stop(got)}"]


def _json_text_only(rec: Recorder) -> list[str | None]:
    # complete() with the strict tool offered but the user asking for prose: the shape
    # complete_json's corrective retry exists for.
    tool = {"name": "emit_grade", "description": "Emit the grade.", "strict": True,
            "input_schema": {**SCHEMA, "additionalProperties": False}}
    llm = AnthropicLLMClient(http_client=rec.client)
    llm.complete(GRADE_SYSTEM, [{"role": "user", "content": GRADE_USER["content"] +
                                 "\n\nReply in one plain sentence. Do not call any tool."}],
                 [tool])
    got = rec.responses[-1]
    if _stop(got) != "end_turn" or "tool_use" in _types(got):
        return [f"expected prose only, got {_stop(got)} {_types(got)}"]
    return [None]


def _json_max_tokens(rec: Recorder) -> list[str | None]:
    llm = AnthropicLLMClient(max_tokens=64, http_client=rec.client)
    try:
        llm.complete_json(GRADE_SYSTEM, [GRADE_USER], schema=SCHEMA, tool_name="emit_grade")
    except StructuredOutputError:
        pass
    got = rec.responses[-1]
    return [None if _stop(got) == "max_tokens" else f"stopped {_stop(got)}"]


def _research(rec: Recorder) -> list[str | None]:
    start = len(rec.responses)
    AnthropicResearcherClient(http_client=rec.client).search(SearchBrief(
        angle="foundations",
        query="Find lecture notes and papers on the gradient descent step-size bound 2/L. "
              "Search at least 5 times before answering."))
    got = rec.responses[start:]
    if len(got) != 2 or _stop(got[0]) != "pause_turn" or _stop(got[1]) != "end_turn":
        why = f"needs exactly pause_turn then end_turn, got {[_stop(c) for c in got]}"
        return [why, why]
    return [None, None]


def _error(rec: Recorder, *, bad_key: bool) -> list[str | None]:
    client = anthropic.Anthropic(
        api_key="sk-ant-api03-recording-invalid-key" if bad_key else
        require_anthropic_api_key(), http_client=rec.client, max_retries=0)
    model = registry.get_model("reasoning") if bad_key else MISSING_MODEL
    try:
        client.messages.create(model=model, max_tokens=16,
                               messages=[{"role": "user", "content": "hi"}])
    except anthropic.APIStatusError:
        pass
    want = 401 if bad_key else 404
    got = rec.responses[-1]
    return [None if got.status == want else f"expected HTTP {want}, got {got.status}"]


SCENARIOS = (
    Scenario("tutor_reply", ("tutor_reply_thinking_text",), _tutor_reply, 1, 600, 300, 20_000),
    Scenario("tutor_tools", ("tutor_tool_use_turn", "tutor_tool_followup_text"),
             _tutor_tools, 2, 900, 400, 20_000),
    Scenario("json_strict", ("json_strict_tool_use",), _json_strict, 2, 700, 300, 20_000),
    Scenario("json_text_only", ("json_text_only",), _json_text_only, 1, 700, 100, 20_000),
    Scenario("json_max_tokens", ("json_max_tokens",), _json_max_tokens, 1, 700, 64, 64),
    Scenario("research", ("research_pause_turn", "research_continuation_end_turn"), _research,
             1 + MAX_PAUSE_CONTINUATIONS, 12_000, 1_500, 16_000,
             max_searches=5 * (1 + MAX_PAUSE_CONTINUATIONS)),
    Scenario("error_401", ("error_401_authentication",),
             lambda rec: _error(rec, bad_key=True), 1, 0, 0, 0),
    Scenario("error_404", ("error_404_model_not_found",),
             lambda rec: _error(rec, bad_key=False), 1, 0, 0, 0),
)


# --- estimate, write, main -----------------------------------------------------------------


def estimate(model: str, scenarios: tuple[Scenario, ...] | list[Scenario]) -> tuple[float, float]:
    """(typical, worst-case) USD for the selected scenarios at list price."""
    if pricing.price_for(model) is None:
        raise SystemExit(f"no known price for {model!r} (llm/pricing.py); pick a priced "
                         "--model so the run can be estimated")
    typical = worst = 0.0
    for s in scenarios:
        typical += s.calls * pricing.cost_usd(model, input_tokens=s.input_tokens,
                                              output_tokens=s.typical_output)
        worst += s.calls * pricing.cost_usd(model, input_tokens=s.input_tokens,
                                            output_tokens=s.max_output)
        worst += s.max_searches * pricing.WEB_SEARCH_USD_PER_SEARCH
        typical += min(s.max_searches, 5) * pricing.WEB_SEARCH_USD_PER_SEARCH
    return typical, worst


def _write(out: Path, name: str, captured: Captured, note: str, model: str,
           redact: Redactor) -> Path:
    doc: dict[str, Any] = {
        "_source": "recorded",
        "_note": f"{note} Recorded {date.today().isoformat()} from {model}.",
    }
    if captured.status != 200:
        doc["_status"] = captured.status
        if captured.headers:
            doc["_headers"] = captured.headers
    doc.update(redact(captured.body))
    path = out / f"{name}.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return path


def _existing_note(out: Path, name: str) -> str:
    try:
        note = json.loads((out / f"{name}.json").read_text()).get("_note", "")
    except (OSError, ValueError):
        return name
    return note.split(" Recorded ", 1)[0]


def _reported_cost(model: str, captured: Captured) -> float:
    u = captured.body.get("usage") if isinstance(captured.body, dict) else None
    if not u:
        return 0.0
    return pricing.cost_usd(
        model,
        input_tokens=u.get("input_tokens", 0),
        output_tokens=u.get("output_tokens", 0),
        cache_creation_input_tokens=u.get("cache_creation_input_tokens") or 0,
        cache_read_input_tokens=u.get("cache_read_input_tokens") or 0,
        web_search_requests=(u.get("server_tool_use") or {}).get("web_search_requests", 0),
    ) or 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--live", action="store_true",
                        help="actually call the Anthropic API (spends money)")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--only", nargs="+", metavar="SCENARIO",
                        choices=[s.name for s in SCENARIOS], help="record only these")
    parser.add_argument("--model", help="model id (default: the reasoning role's model)")
    parser.add_argument("--out", type=Path, default=FIXTURES, help="fixture directory")
    args = parser.parse_args(argv)

    # The fixtures are Anthropic API responses: the clients must not be pointed elsewhere.
    if current_backend_name() != BACKEND_ANTHROPIC:
        print("This records Anthropic API responses, so it runs only on the Anthropic backend. "
              "Unset AA_LLM_BACKEND (it is set to "
              f"'{current_backend_name()}') and try again. Nothing was sent.", file=sys.stderr)
        return 2

    if args.model:
        registry._settings.settings.reasoning_model = args.model
    model = registry.get_model("reasoning")
    selected = [s for s in SCENARIOS if not args.only or s.name in args.only]
    typical, worst = estimate(model, selected)
    print(f"Model: {model}")
    for s in selected:
        print(f"  {s.name:<16} up to {s.calls} call(s) -> {', '.join(s.fixtures)}")
    print(f"Estimated cost: about ${typical:.2f}; at most ${worst:.2f} if every call hits "
          "its max_tokens cap and every allowed web search runs.")
    if not args.live:
        print("Refusing to call the API without --live. Nothing was sent.", file=sys.stderr)
        return 2
    if not args.yes and input("Proceed and spend that? [y/N] ").strip().lower() != "y":
        print("Aborted. Nothing was sent.")
        return 1

    require_anthropic_api_key()
    usage.set_usage_bind(None)  # fixtures run: don't write usage rows into the app database
    args.out.mkdir(parents=True, exist_ok=True)
    recorder, redact = Recorder(), Redactor()
    spent = 0.0
    for s in selected:
        start = len(recorder.responses)
        try:
            problems = s.run(recorder)
        except Exception as exc:  # noqa: BLE001 - report and move on to the next scenario
            problems = [f"failed: {type(exc).__name__}: {exc}"] * len(s.fixtures)
        captured = recorder.responses[start:]
        spent += sum(_reported_cost(model, c) for c in captured)
        if s.name == "research":  # the paused turn is the first response, the end the last
            captured = [captured[0], captured[-1]] if len(captured) >= 2 else captured
        for i, name in enumerate(s.fixtures):
            problem = problems[i] if i < len(problems) else "no response captured"
            if problem is None and i < len(captured):
                path = _write(args.out, name, captured[i], _existing_note(args.out, name),
                              model, redact)
                print(f"  wrote {path}")
            else:
                print(f"  kept {name}.json: {problem or 'no response captured'}")
    print(f"Done. Responses reported about ${spent:.4f} at list price.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
