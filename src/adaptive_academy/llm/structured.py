"""Structured JSON output from an LLM, with graceful degradation.

If the client implements `complete_json` (forced tool use against a JSON schema — a hard
guarantee of well-formed, correctly-shaped output), use it. Otherwise fall back to a normal
text completion parsed with the tolerant `extract_json`. This keeps the Agent SDK client (which
has no forced-tool path) and lightweight test fakes working unchanged, while the API-key client
gets the schema guarantee.

Note: structured output guarantees SHAPE, not length — a response that exceeds max_tokens still
truncates. Pair it with an adequate token ceiling and a scope-bounded prompt.
"""

import json
from typing import Any

from adaptive_academy.jsonout import extract_json


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
    text = llm.complete(system=system, messages=messages, tools=[]).text
    return json.loads(extract_json(text))
