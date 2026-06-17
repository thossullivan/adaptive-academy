import json

from adaptive_academy.jsonout import extract_json


def test_plain_json_passes_through():
    assert json.loads(extract_json('{"a": 1}')) == {"a": 1}


def test_fenced_json():
    assert json.loads(extract_json('```json\n{"a": 1}\n```')) == {"a": 1}


def test_preamble_before_fence_is_tolerated():
    # The exact failure the old startswith-only stripper let through -> 502.
    raw = 'Here is the JSON:\n```json\n{"score": 0.5}\n```'
    assert json.loads(extract_json(raw)) == {"score": 0.5}


def test_prose_wrapped_without_fences():
    assert json.loads(extract_json('Sure! {"x": [1, 2]} hope that helps')) == {"x": [1, 2]}


def test_array_payload():
    assert json.loads(extract_json('```\n[{"url": "u"}]\n```')) == [{"url": "u"}]


def test_malformed_still_raises():
    # We don't swallow genuinely broken payloads — caller's json.loads surfaces it.
    import pytest

    with pytest.raises(json.JSONDecodeError):
        json.loads(extract_json("not json at all"))
