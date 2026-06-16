from adaptive_academy.engine.anchors import parse_anchors_json


def test_parse_plain_and_fenced():
    payload = ('{"anchors": [{"question": "q", "reference_answer": "a", '
               '"key_points": ["k1", "k2"], "concept": "softmax"}]}')
    out = parse_anchors_json(payload)
    assert len(out) == 1
    assert out[0].question == "q"
    assert out[0].key_points == ["k1", "k2"]
    assert out[0].concept_name == "softmax"

    fenced = '```json\n{"anchors": []}\n```'
    assert parse_anchors_json(fenced) == []
