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


def test_load_bearing_with_key_concepts_keeps_only_generated_concepts():
    # Spec §2.3: "A generated Concept is load-bearing iff it appears as a prerequisite".
    # A prerequisite that is not a key concept never becomes a Concept row, so it has
    # nothing to revisit or self-explain against.
    prereq = {
        "self-attention": ["Linear Algebra", "softmax", "Big-O complexity"],
        "backprop": ["calculus", "linear algebra"],
        "softmax": ["softmax"],  # a self-loop is not a dependency
    }
    key = ["self-attention", "backprop", "softmax", "linear algebra"]
    assert load_bearing_concepts(prereq, key_concepts=key) == {"linear algebra", "softmax"}


def test_dependents_of_maps_prerequisite_to_its_dependents():
    from adaptive_academy.engine.curriculum import dependents_of

    prereq = {"b": ["A", "x"], "c": ["a", "b"], "a": ["a"]}
    assert dependents_of(prereq, ["a", "b", "c"]) == {"a": {"b", "c"}, "b": {"c"}}
