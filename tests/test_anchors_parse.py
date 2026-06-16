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


def test_anthropic_anchor_client_parses_completion():
    from adaptive_academy.llm.anchor_types import AnchorBrief
    from adaptive_academy.llm.anthropic_anchor import AnthropicAnchorClient
    from adaptive_academy.llm.scripted_client import ScriptedLLMClient
    from adaptive_academy.llm.types import LLMResponse

    llm = ScriptedLLMClient([LLMResponse(text='{"anchors": [{"question": "q", '
                            '"reference_answer": "a", "key_points": ["k"], '
                            '"concept": "softmax"}]}')])
    client = AnthropicAnchorClient(llm=llm)
    out = client.generate(AnchorBrief(source_doc_id=1, title="t", summary="s",
                                      url="u", key_concepts=["softmax"]))
    assert out[0].question == "q" and out[0].concept_name == "softmax"
    assert len(llm.calls) == 1
