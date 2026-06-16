# tests/test_curriculum_concepts.py
from adaptive_academy.engine.curriculum import load_bearing_concepts


def test_load_bearing_is_anything_depended_upon():
    prereq = {
        "self-attention": ["linear algebra", "softmax"],
        "backprop": ["calculus", "linear algebra"],
        "LoRA": ["linear algebra"],
    }
    lb = load_bearing_concepts(prereq)
    assert lb == {"linear algebra", "softmax", "calculus"}


def test_load_bearing_empty():
    assert load_bearing_concepts({}) == set()
    assert load_bearing_concepts({"a": []}) == set()
