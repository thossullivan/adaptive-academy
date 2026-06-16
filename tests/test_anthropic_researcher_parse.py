from adaptive_academy.llm.anthropic_researcher import parse_sources_json


def test_parse_sources_json_plain():
    text = '[{"title":"A","url":"https://a.com","tier":1,"summary":"s","why":"w","relevance":0.9}]'
    out = parse_sources_json(text)
    assert len(out) == 1
    assert out[0].title == "A"
    assert out[0].tier == 1
    assert out[0].relevance == 0.9


def test_parse_sources_json_with_fence_and_missing_fields():
    text = '```json\n[{"title":"B","url":"https://b.com"}]\n```'
    out = parse_sources_json(text)
    assert out[0].tier == 3  # default
    assert out[0].relevance == 0.0


def test_parse_sources_json_garbage_returns_empty():
    assert parse_sources_json("not json at all") == []
