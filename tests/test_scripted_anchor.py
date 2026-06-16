from adaptive_academy.llm.anchor_types import AnchorBrief, RawAnchor
from adaptive_academy.llm.scripted_anchor import ScriptedAnchorClient


def test_scripted_returns_by_source_and_records_calls():
    anchors = {1: [RawAnchor(question="q1", reference_answer="a1",
                             key_points=["k"], concept_name="softmax")]}
    client = ScriptedAnchorClient(anchors)
    brief = AnchorBrief(source_doc_id=1, title="t", summary="s", url="u",
                        key_concepts=["softmax"])
    out = client.generate(brief)
    assert out[0].question == "q1"
    assert client.calls == [1]
    assert client.generate(AnchorBrief(source_doc_id=99, title="", summary="",
                                       url="", key_concepts=[])) == []
