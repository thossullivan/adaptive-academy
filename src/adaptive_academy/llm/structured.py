"""Structured JSON output from an LLM, with graceful degradation.

If the client implements `complete_json` (a strict tool against a JSON schema — a hard
guarantee of well-formed, correctly-shaped output on a strict model, and checked against the
schema on any other; see llm/anthropic_client.py, and llm/strict_schema.py for the supported
schema subset), use it. Otherwise fall back to a normal text completion parsed with the
tolerant `extract_json`. This keeps the Agent SDK client (which has no strict-tool path) and
lightweight test fakes working, while the API-key client gets the schema guarantee.

The text path has no schema guarantee at all, so its answer gets the same check as a
non-strict tool answer (llm/schema_check.py, against the strict-shaped schema): a mismatch
gets one corrective turn naming the violations, and a second mismatch is
StructuredOutputError("schema_mismatch"), a legible 502 (category invalid_output).

Note: structured output guarantees SHAPE, not length — a response that exceeds max_tokens still
truncates. Pair it with an adequate token ceiling and a scope-bounded prompt.
"""

import json
from typing import Any

from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.schema_check import describe_violations, schema_violations
from adaptive_academy.llm.strict_schema import to_strict_schema
from adaptive_academy.llm.types import StructuredOutputError
from adaptive_academy.prompts import SCHEMA_RESEND_TEXT, STRUCTURED_SCHEMA_RETRY


SCOUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "rationale": {"type": "string"},
                    "candidate_kind": {
                        "type": "string",
                        "enum": ["frontier", "orphan_term", "orphan_note", "extension"],
                    },
                    "evidence_indexes": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "integer", "minimum": 0},
                    },
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "title",
                    "rationale",
                    "candidate_kind",
                    "evidence_indexes",
                    "score",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def structured_json(
    llm: Any,
    system: str,
    messages: list[dict[str, Any]],
    *,
    schema: dict[str, Any],
    tool_name: str,
) -> dict[str, Any]:
    complete_json = getattr(llm, "complete_json", None)
    if callable(complete_json):
        return complete_json(system=system, messages=messages, schema=schema, tool_name=tool_name)
    shape = to_strict_schema(schema)
    attempt = list(messages)
    for retries_left in (1, 0):
        text = llm.complete(system=system, messages=attempt, tools=[]).text
        data = json.loads(extract_json(text))
        violations = schema_violations(data, shape)
        if not violations:
            return data
        listed = describe_violations(violations)
        if not retries_left:
            raise StructuredOutputError(
                "schema_mismatch",
                f"structured answer did not match its schema after a corrective retry:\n{listed}")
        # Append-only: the model's own answer, then what was wrong with it.
        attempt = [*messages, {"role": "assistant", "content": text},
                   {"role": "user", "content": STRUCTURED_SCHEMA_RETRY.format(
                       violations=listed, resend=SCHEMA_RESEND_TEXT)}]
    raise AssertionError("unreachable")
