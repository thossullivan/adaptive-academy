"""The dependency-free schema check (llm/schema_check.py) on every schema the app sends to a
model, and on each keyword llm/strict_schema.py can produce."""

import copy

import pytest

from adaptive_academy.engine.curriculum import CURRICULUM_SCHEMA
from adaptive_academy.engine.program_research import PROGRAM_SCHEMA
from adaptive_academy.engine.revision import REVISION_SCHEMA
from adaptive_academy.engine.solution_guard import GUARD_SCHEMA
from adaptive_academy.llm.schema_check import describe_violations, schema_violations
from adaptive_academy.llm.strict_schema import to_strict_schema
from adaptive_academy.llm.structured import SCOUT_SCHEMA

CURRICULUM_OK = {
    "overview": "A path",
    "phases": [{
        "title": "P1", "est_hours": "Weeks 1-2", "flags": ["optional"],
        "items": [{"type": "read", "text": "paper", "concept_refs": ["x"]},
                  {"type": "build", "text": "toy"}],
        "deliverable": {"kind": "blog", "text": "post", "acceptance_criteria": ["clear"]},
    }],
    "sidebars": [{"kind": "math_refresh", "title": "Math", "body": "la"}],
}
PROGRAM_OK = {"milestones": [{
    "title": "M", "success_criteria": "s", "depends_on": [0],
    "topics": [{"title": "T", "why": "w", "source_urls": ["https://e.com"]}, {"title": "U"}],
}]}
SCOUT_OK = {"items": [{"title": "T", "rationale": "r", "candidate_kind": "frontier",
                       "evidence_indexes": [0, 2], "score": 0.5}]}
GUARD_OK = {"gives_away_solution": False, "learner_attempted": True, "reason": "hint only"}
REVISION_OK = {"map_health": "ok", "changes": [
    {"kind": "add_milestone", "why": "gap", "source_urls": [],
     "payload": {"title": "New", "after_milestone_id": None, "topics": [{"title": "T"}]}},
    {"kind": "prune_topic", "why": "stale", "payload": {"link_id": 3}},
    {"kind": "add_milestone", "why": "gap", "payload": {"title": "N", "after_milestone_id": 2}},
]}

# (schema, a valid answer, how to break one value's type, the path that names it)
APP_SCHEMAS = {
    "curriculum": (CURRICULUM_SCHEMA, CURRICULUM_OK,
                   lambda d: d["phases"].__setitem__(0, "Phase 1: basics"), "$.phases[0]"),
    "program": (PROGRAM_SCHEMA, PROGRAM_OK,
                lambda d: d["milestones"][0]["topics"].__setitem__(1, "U"),
                "$.milestones[0].topics[1]"),
    "scout": (SCOUT_SCHEMA, SCOUT_OK,
              lambda d: d["items"][0].__setitem__("evidence_indexes", "0, 2"),
              "$.items[0].evidence_indexes"),
    "guard": (GUARD_SCHEMA, GUARD_OK,
              lambda d: d.__setitem__("gives_away_solution", "no"), "$.gives_away_solution"),
    "revision": (REVISION_SCHEMA, REVISION_OK,
                 lambda d: d["changes"][0]["payload"].__setitem__("after_milestone_id", "2"),
                 "$.changes[0].payload.after_milestone_id"),
}


@pytest.mark.parametrize("name", sorted(APP_SCHEMAS))
def test_a_valid_answer_passes_every_app_schema(name):
    schema, ok, _, _ = APP_SCHEMAS[name]
    assert schema_violations(ok, to_strict_schema(schema)) == []


@pytest.mark.parametrize("name", sorted(APP_SCHEMAS))
def test_a_type_mismatch_fails_with_its_path(name):
    schema, ok, breaker, path = APP_SCHEMAS[name]
    bad = copy.deepcopy(ok)
    breaker(bad)
    found = schema_violations(bad, to_strict_schema(schema))
    assert found, name
    assert found[0].path == path
    assert path in describe_violations(found)


def test_the_live_shape_names_the_phase_and_what_it_got():
    bad = copy.deepcopy(CURRICULUM_OK)
    bad["phases"].append("Phase 2: transformers")
    [v] = schema_violations(bad, to_strict_schema(CURRICULUM_SCHEMA))
    assert str(v) == "$.phases[1]: expected object, got string 'Phase 2: transformers'"


@pytest.mark.parametrize("value", ["a string", ["a", "list"], None, 3])
def test_a_non_object_answer_fails_at_the_root(value):
    [v] = schema_violations(value, to_strict_schema(GUARD_SCHEMA))
    assert v.path == "$" and v.message.startswith("expected object")


def test_required_additional_enum_and_min_items():
    schema = to_strict_schema(SCOUT_SCHEMA)
    bad = {"items": [{"title": "T", "rationale": "r", "candidate_kind": "elsewhere",
                      "evidence_indexes": [], "extra": 1}], "note": "x"}
    messages = {str(v) for v in schema_violations(bad, schema)}
    assert messages == {
        "$: unexpected property 'note'",
        "$.items[0]: missing required property 'score'",
        "$.items[0]: unexpected property 'extra'",
        "$.items[0].candidate_kind: 'elsewhere' is not one of 'frontier', 'orphan_term', "
        "'orphan_note', 'extension'",
        "$.items[0].evidence_indexes: expected at least 1 item(s), got 0",
    }


@pytest.mark.parametrize("value,ok", [
    (3, True), (True, False), (3.0, False), ("3", False), (None, False)])
def test_integer_is_a_json_integer_only(value, ok):
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"],
              "additionalProperties": False}
    assert (schema_violations({"n": value}, schema) == []) is ok


@pytest.mark.parametrize("value,ok", [(0.5, True), (1, True), (False, False), ("0.5", False)])
def test_number_accepts_int_and_float_but_not_bool(value, ok):
    schema = {"type": "number"}
    assert (schema_violations(value, schema) == []) is ok


@pytest.mark.parametrize("value,ok", [("x", True), (None, True), (1, False)])
def test_nullable_by_type_list_and_by_any_of(value, ok):
    assert (schema_violations(value, {"type": ["string", "null"]}) == []) is ok
    assert (schema_violations(value, {"anyOf": [{"type": "string"}, {"type": "null"}]})
            == []) is ok


def test_any_of_reports_the_one_variant_of_the_right_type():
    schema = {"anyOf": [{"type": "null"}, {"type": "object", "properties": {
        "a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}]}
    [v] = schema_violations({"a": 1}, schema)
    assert str(v) == "$.a: expected string, got integer 1"


def test_refs_to_defs_resolve():
    schema = to_strict_schema({
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "required": ["node"],
        "$defs": {"Node": {"type": "object", "properties": {"v": {"type": "integer"}},
                           "required": ["v"]}},
    })
    assert schema_violations({"node": {"v": 1}}, schema) == []
    [v] = schema_violations({"node": {"v": "1"}}, schema)
    assert v.path == "$.node.v"


def test_all_of_checks_every_part():
    schema = {"allOf": [{"type": "string"}, {"enum": ["a", "b"]}]}
    assert schema_violations("a", schema) == []
    assert schema_violations("c", schema)


def test_an_unsupported_keyword_is_a_schema_bug_not_a_pass():
    with pytest.raises(ValueError, match="not supported"):
        schema_violations("x", {"type": "string", "pattern": "^x$"})


def test_the_limit_caps_the_list_and_the_description_says_so():
    schema = to_strict_schema(CURRICULUM_SCHEMA)
    bad = {"overview": "o", "phases": [f"phase {i}" for i in range(30)]}
    found = schema_violations(bad, schema, limit=20)
    assert len(found) == 20
    text = describe_violations(found, shown=3)
    assert text.count("\n") == 3 and text.endswith("(and more not shown)")


# The `jsonschema` package is only a transitive dependency (claude-agent-sdk -> mcp), so it is
# an oracle here, not a runtime dependency. Integer-valued floats are left out: this check
# rejects 3.0 for "integer" on purpose (see llm/schema_check.py).
_MUTATIONS = [
    lambda d: None,
    lambda d: d.pop("overview"),
    lambda d: d.__setitem__("phases", "none"),
    lambda d: d["phases"].append("Phase 2"),
    lambda d: d["phases"].append(None),
    lambda d: d["phases"][0].__setitem__("items", {"type": "read"}),
    lambda d: d["phases"][0]["items"].append("read a paper"),
    lambda d: d["phases"][0]["items"][0].__setitem__("type", "quiz"),
    lambda d: d["phases"][0]["items"][0].__setitem__("concept_refs", "x"),
    lambda d: d["phases"][0]["items"][0]["concept_refs"].append(7),
    lambda d: d["phases"][0].__setitem__("deliverable", "a blog post"),
    lambda d: d["phases"][0]["deliverable"].pop("kind"),
    lambda d: d["phases"][0].__setitem__("flags", ["optional", "maybe"]),
    lambda d: d["phases"][0].__setitem__("extra", True),
    lambda d: d["sidebars"].__setitem__(0, ["math"]),
    lambda d: d.__setitem__("overview", None),
]


@pytest.mark.parametrize("i", range(len(_MUTATIONS)))
def test_agrees_with_jsonschema_on_curriculum_answers(i):
    jsonschema = pytest.importorskip("jsonschema")
    schema = to_strict_schema(CURRICULUM_SCHEMA)
    answer = copy.deepcopy(CURRICULUM_OK)
    _MUTATIONS[i](answer)
    oracle_ok = jsonschema.Draft202012Validator(schema).is_valid(answer)
    assert (schema_violations(answer, schema) == []) is oracle_ok
