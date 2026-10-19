"""JSON Schema → the subset strict tool use accepts.

Strict tools (`strict: true`) compile the input schema into a grammar, which supports only part
of JSON Schema: every object needs `additionalProperties: false`, and numerical, string-length
and most array constraints (`minimum`, `minLength`, `maxItems`, `uniqueItems`, …) are rejected
with a 400. The docs recommend the SDK's `transform_schema()` for this: it adds
`additionalProperties: false`, drops unsupported keywords and appends them to the field's
description as a hint. Engine code keeps enforcing those constraints after parsing.

One case the transform can't fix: an object with no declared properties. Under strict mode it
could only ever be `{}`, so its content would be silently lost — that is a schema bug, raised
here so it fails in tests rather than in production.
"""

from typing import Any

from anthropic import transform_schema


def _assert_no_open_objects(node: Any, path: str = "$") -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") == "object" and not node.get("properties"):
        raise ValueError(
            f"{path}: object schema has no properties; strict tool use would force it to "
            "be empty. Declare its properties."
        )
    for key, sub in (node.get("properties") or {}).items():
        _assert_no_open_objects(sub, f"{path}.{key}")
    if "items" in node:
        _assert_no_open_objects(node["items"], f"{path}[]")
    for key in ("anyOf", "allOf"):
        for i, sub in enumerate(node.get(key) or []):
            _assert_no_open_objects(sub, f"{path}.{key}[{i}]")
    for name, sub in (node.get("$defs") or {}).items():
        _assert_no_open_objects(sub, f"$defs.{name}")


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A strict-tool-compatible copy of `schema` (the input is not modified)."""
    strict = transform_schema(schema)
    _assert_no_open_objects(strict)
    return strict
