from adaptive_academy.engine.remediate import parse_remediation_json


def test_parse_plain_json():
    d = parse_remediation_json(
        '{"items": [{"type": "build", "text": "t"}], "revisit": {"text": "r"}}')
    assert d.items == [{"type": "build", "text": "t"}]
    assert d.revisit == {"text": "r"}


def test_parse_strips_fences_and_handles_missing():
    d = parse_remediation_json('```json\n{"items": []}\n```')
    assert d.items == []
    assert d.revisit is None
