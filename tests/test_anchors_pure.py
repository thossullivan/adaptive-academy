from adaptive_academy.engine.anchors import (
    anchor_key,
    dedupe_anchors,
    match_concept,
)
from adaptive_academy.llm.anchor_types import RawAnchor


def test_anchor_key_normalizes():
    assert anchor_key("  Why Does Softmax  Work? ") == anchor_key("why does softmax work?")
    assert anchor_key("a b") != anchor_key("a c")


def test_match_concept_case_insensitive_exact():
    concepts = ["Self-Attention", "softmax"]
    assert match_concept("softmax", concepts) == "softmax"
    assert match_concept("SELF-ATTENTION", concepts) == "Self-Attention"
    assert match_concept("layernorm", concepts) is None


def test_dedupe_anchors_on_source_and_question():
    a = RawAnchor(question="Q?", concept_name="softmax")
    b = RawAnchor(question=" q?  ", concept_name="softmax")
    c = RawAnchor(question="other?", concept_name="softmax")
    out = dedupe_anchors([(1, a), (1, b), (1, c), (2, a)])
    assert len(out) == 3
