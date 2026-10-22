"""Check a structured answer against the strict-shaped schema it was asked for.

A `strict: true` tool guarantees its input matches the schema. A model without strict tool use
(every non-Claude model through OpenRouter, and Claude before 4.5; llm/model_catalog.py) gets
the same schema without that guarantee: a live DeepSeek run returned a curriculum phase as a
string, and the parser crashed on it. llm/anthropic_client.py and llm/structured.py run this
check on those answers before any caller sees them.

Dependency-free on purpose. The `jsonschema` package is installed, but only as a transitive
dependency (mcp, via claude-agent-sdk), and the schemas checked here are a small closed subset:
everything goes through llm/strict_schema.py (the SDK's `transform_schema`), whose output uses
only the keywords below. A keyword outside that set raises ValueError, so a schema this check
can't read fails in tests (tests/test_schema_check.py runs every app schema), not silently.

Stricter than JSON Schema in one place: an `integer` must be a JSON integer, not 3.0, because
the callers use these values as list indexes and ids (engine/scout.py rejects a float index).
`format` is not checked (it shapes a strict grammar; here it is only a hint), nor is
`description` or `title`.
"""

from dataclasses import dataclass
from typing import Any

# Keywords llm/strict_schema.py can produce (anthropic.transform_schema), and nothing else.
_KNOWN = frozenset({
    "$defs", "$ref", "type", "anyOf", "allOf", "enum", "description", "title", "properties",
    "additionalProperties", "required", "format", "items", "minItems",
})

_JSON_TYPE_NAMES = {
    dict: "object", list: "array", str: "string", bool: "boolean", type(None): "null",
    int: "integer", float: "number",
}


@dataclass(frozen=True)
class Violation:
    path: str  # JSON path of the offending value, "$" for the whole answer
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _json_type(value: Any) -> str:
    return _JSON_TYPE_NAMES.get(type(value), type(value).__name__)


def _is_type(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise ValueError(f"unsupported schema type {type_name!r}")


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


class _Checker:
    def __init__(self, root: dict[str, Any], limit: int):
        self._root = root
        self._limit = limit
        self.found: list[Violation] = []

    def full(self) -> bool:
        return len(self.found) >= self._limit

    def add(self, path: str, message: str) -> None:
        if not self.full():
            self.found.append(Violation(path, message))

    def resolve(self, ref: str) -> dict[str, Any]:
        prefix = "#/$defs/"
        defs = self._root.get("$defs") or {}
        if not ref.startswith(prefix) or ref[len(prefix):] not in defs:
            raise ValueError(f"unsupported or unknown $ref {ref!r}")
        return defs[ref[len(prefix):]]

    def matches(self, value: Any, schema: dict[str, Any]) -> bool:
        """Whether `value` fits `schema`, without recording anything (for anyOf)."""
        probe = _Checker(self._root, limit=1)
        probe.check(value, schema, "$")
        return not probe.found

    def check(self, value: Any, schema: dict[str, Any], path: str) -> None:
        if self.full():
            return
        unknown = set(schema) - _KNOWN
        if unknown:
            raise ValueError(f"schema keyword(s) not supported here: {sorted(unknown)}")
        if "$ref" in schema:
            self.check(value, self.resolve(schema["$ref"]), path)
            return
        if "anyOf" in schema:
            variants = schema["anyOf"]
            if not any(self.matches(value, v) for v in variants):
                fits = [v for v in variants if self._type_fits(value, v)]
                if len(fits) == 1:
                    # One variant has the right type: its own complaint is the useful one.
                    self.check(value, fits[0], path)
                else:
                    self.add(path, f"{_json_type(value)} {_short(value)} matches none of "
                                   "the allowed shapes")
        for sub in schema.get("allOf") or []:
            self.check(value, sub, path)
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            fitting = [t for t in types if _is_type(value, t)]
            if not fitting:
                self.add(path, f"expected {' or '.join(types)}, got {_json_type(value)} "
                               f"{_short(value)}")
                return
        if "enum" in schema and value not in schema["enum"]:
            allowed = ", ".join(repr(v) for v in schema["enum"])
            self.add(path, f"{_short(value)} is not one of {allowed}")
        if isinstance(value, dict):
            self._check_object(value, schema, path)
        elif isinstance(value, list):
            self._check_array(value, schema, path)

    def _type_fits(self, value: Any, schema: dict[str, Any]) -> bool:
        if "$ref" in schema:
            return self._type_fits(value, self.resolve(schema["$ref"]))
        if "type" not in schema:
            return True
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        return any(_is_type(value, t) for t in types)

    def _check_object(self, value: dict, schema: dict[str, Any], path: str) -> None:
        properties = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in value:
                self.add(path, f"missing required property {name!r}")
        for name, item in value.items():
            if name in properties:
                self.check(item, properties[name], f"{path}.{name}")
            elif schema.get("additionalProperties") is False:
                self.add(path, f"unexpected property {name!r}")

    def _check_array(self, value: list, schema: dict[str, Any], path: str) -> None:
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            self.add(path, f"expected at least {min_items} item(s), got {len(value)}")
        items = schema.get("items")
        if items is not None:
            for i, item in enumerate(value):
                self.check(item, items, f"{path}[{i}]")


def schema_violations(value: Any, schema: dict[str, Any], *, limit: int = 20) -> list[Violation]:
    """Where `value` breaks `schema` (a llm/strict_schema.py output), first `limit` only.

    An empty list means the value fits. Raises ValueError for a schema keyword this check
    doesn't support (a schema bug, not a model error).
    """
    checker = _Checker(schema, limit)
    checker.check(value, schema, "$")
    return checker.found


def describe_violations(violations: list[Violation], *, shown: int = 5) -> str:
    """The first few violations, one per line, for a correction message or an error."""
    lines = [f"- {v}" for v in violations[:shown]]
    if len(violations) > shown:
        lines.append("- (and more not shown)")
    return "\n".join(lines)
