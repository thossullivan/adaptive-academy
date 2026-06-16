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


def test_researcher_token_budget_is_generous(monkeypatch):
    # 2048 truncated web-search JSON mid-string (stop_reason=max_tokens) -> 0 sources
    # across every angle. The budget must be large enough to hold search + JSON output.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
    assert AnthropicResearcherClient()._max_tokens >= 8192


def test_parse_sources_json_truncated_returns_empty():
    # A response cut off mid-string must not crash the fan-out — it degrades to [].
    text = '[{"title":"A","url":"https://a.com","summary":"this got cut o'
    assert parse_sources_json(text) == []
