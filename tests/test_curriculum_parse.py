# tests/test_curriculum_parse.py
import json

from adaptive_academy.engine.curriculum import parse_curriculum_json


def test_parses_full_payload():
    payload = json.dumps({
        "overview": "ov",
        "phases": [{
            "title": "P1", "est_hours": "Weeks 1-2", "flags": ["optional"],
            "items": [{"type": "read", "text": "paper", "concept_refs": ["x"]}],
            "deliverable": {"kind": "blog", "text": "post", "acceptance_criteria": ["clear"]},
        }],
        "sidebars": [{"kind": "math_refresh", "title": "Math", "body": "la"}],
    })
    tv = parse_curriculum_json(payload, title="Topic T")
    assert tv.title == "Topic T"
    assert tv.overview == "ov"
    assert tv.phases[0].flags == ["optional"]
    assert tv.phases[0].items[0].concept_refs == ["x"]
    assert tv.phases[0].deliverable.kind == "blog"
    assert tv.sidebars[0].kind == "math_refresh"


def test_strips_code_fences_and_defaults():
    tv = parse_curriculum_json('```json\n{"phases": [{"title": "P"}]}\n```', title="T")
    assert tv.phases[0].title == "P"
    assert tv.phases[0].items == [] and tv.phases[0].deliverable is None
    assert tv.overview == "" and tv.sidebars == []
