"""Robust extraction of JSON from model text — one shared home (was copy-pasted 9×).

The old per-module `_strip_fences` only stripped when the text *started* with a code fence,
so the single most common real failure — a one-line preamble before the fence ("Here is the
JSON:\\n```json…") — sailed through to `json.loads` and 502'd the user (a silent grade-loss on
the Assessor path). This tolerates a leading preamble and prose on either side, and falls back
to the original so a genuinely malformed payload still raises a real parse error.
"""

from typing import Any

from adaptive_academy.llm.types import StructuredOutputError


def extract_json(text: str) -> str:
    """Pull the JSON object/array out of model output that may be fenced and/or prose-wrapped."""
    s = (text or "").strip()

    # If fenced anywhere (even after a preamble), take the first fenced block's body.
    if "```" in s:
        parts = s.split("```")
        if len(parts) >= 2:
            s = parts[1]
            lead = s.lstrip()
            if lead[:4].lower() == "json":
                s = lead[4:]
        s = s.strip()

    # If prose still brackets the JSON, trim to the outermost object/array span.
    if not s.startswith(("{", "[")):
        opens = [i for i in (s.find("{"), s.find("[")) if i != -1]
        closes = [i for i in (s.rfind("}"), s.rfind("]")) if i != -1]
        if opens and closes:
            a, b = min(opens), max(closes)
            if b > a:
                s = s[a : b + 1]

    return s.strip()


# Shape guards for parsed model JSON. A model without strict tool use, or any text-parsed
# answer, can put a string where an object belongs (the live failure: a curriculum phase as
# a string). Parsers skip such entries; an answer with nothing usable is a
# StructuredOutputError (a legible 502), never an AttributeError (a bare 500).


def str_items(value: Any) -> list[str]:
    """The string entries of a JSON array; anything that isn't a list gives []."""
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def require_object(data: Any, what: str) -> dict:
    """`data` if it is a JSON object, else StructuredOutputError("malformed")."""
    if not isinstance(data, dict):
        raise StructuredOutputError(
            "malformed", f"{what}: expected a JSON object, got {type(data).__name__}")
    return data


def require_list(data: dict, key: str, what: str) -> list:
    """`data[key]` as a list ([] when absent or null), else StructuredOutputError."""
    value = data.get(key) or []
    if not isinstance(value, list):
        raise StructuredOutputError(
            "malformed", f"{what}: {key!r} should be a list, got {type(value).__name__}")
    return value


def dropped_summary(paths: list[str], shown: int = 5) -> str:
    """An AgentEvent detail for the entries a parser skipped, by JSON path."""
    noun = "entry" if len(paths) == 1 else "entries"
    more = " …" if len(paths) > shown else ""
    return f"WARN {len(paths)} malformed {noun} skipped: {', '.join(paths[:shown])}{more}"
