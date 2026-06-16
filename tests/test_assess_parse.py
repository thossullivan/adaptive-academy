# tests/test_assess_parse.py
import json

from adaptive_academy.engine.assess import parse_grade_json, parse_rubric_json


def test_parse_rubric():
    payload = json.dumps({"criteria": ["c1"], "must_include": ["softmax"],
                          "strong_signs": ["s"], "weak_signs": ["w"], "source_refs": ["S"]})
    r = parse_rubric_json(payload)
    assert r.must_include == ["softmax"] and r.criteria == ["c1"]


def test_parse_grade_with_fences_and_defaults():
    g = parse_grade_json('```json\n{"score": 0.7, "verdict": "v", "gaps": ["x"]}\n```')
    assert g.score == 0.7 and g.verdict == "v" and g.gaps == ["x"]
    assert g.confidence_actual is None  # absent -> None
    g2 = parse_grade_json('{"score": "bad"}')  # non-numeric score -> 0.0 default
    assert g2.score == 0.0
