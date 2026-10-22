"""Concept names are short noun phrases, never the answer (engine/concept_names.py).

A concept name is shown on the Tutor page and pasted into probes ("Explain *why* {concept}
works"), so a name that states a formula or a result puts the answer on screen before the
learner has tried. The live failure (DeepSeek via OpenRouter, "Gradient descent for linear
regression") produced names like the EVIDENCE strings below.
"""

import pytest

from adaptive_academy.engine.concept_names import (
    MAX_NAME_CHARS,
    MAX_NAME_WORDS,
    check_names,
    name_problems,
    repair_name,
    repair_names,
)
from adaptive_academy.engine.output_checks import FAIL

EVIDENCE = [
    "Gradient of the cost: ∇J(θ)=Xᵀ(Xθ−y) (divided by m if using the averaged cost)",
    "Least-squares cost J(θ)=½‖Xθ−y‖² (or 1/2m variant) is a convex quadratic with a "
    "single global minimum",
    "Stability threshold: guaranteed descent for α ≤ 1/L where L = λmax(XᵀX)/m; "
    "divergence once α exceeds roughly 2/L",
]


def _ids(name) -> set[str]:
    return {r.rule_id for r in name_problems(name)}


# ── Rules ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Causal Self-Attention", "L2 norm", "Big-O", "Big-O complexity of matrix operations",
    "1-D minimization along a direction", "Batch gradient descent update", "softmax",
    "β-VAE", "λ-calculus", "α-β pruning", "TCP/IP", "I/O scheduling", "C++ templates",
    "A* search", "GPT-2", "Attention (transformers)", "Q-learning", "Singular value decomposition",
    "Sampling: Temperature and Top-k",
])
def test_short_noun_phrases_pass(name):
    assert name_problems(name) == []


@pytest.mark.parametrize("name,rule", [
    ("", "N1"), ("   ", "N1"), (None, "N1"), (42, "N1"), (["a"], "N1"),
    ("convergence rate of gradient descent on strongly convex quadratic objectives", "N2"),
    ("x" * (MAX_NAME_CHARS + 1), "N2"),
    ("∇J(θ)", "N3"), ("cost = loss", "N3"), ("α ≤ 1/L", "N3"), ("XᵀX", "N3"),
    ("‖x‖ squared", "N3"), ("x² term", "N3"), ("½ factor", "N3"), ("λmax", "N3"),
    ("learning rate α", "N3"), ("softmax(QK^T)", "N3"), ("O(n) lookup", "N3"),
    ("step size 1/L", "N3"), ("x^2", "N3"), ("$\\nabla J$", "N3"), ("Q·K score", "N3"),
    ("Gradient of the cost: the transpose times residual", "N4"),
    ("Momentum; damps oscillation", "N4"), ("Momentum — damps oscillation", "N4"),
    ("Momentum - damps oscillation", "N4"),
    ("Stability threshold: guaranteed descent for small steps", "N4"),
    ("Least-squares cost is convex", "N5"), ("Gradient descent converges", "N5"),
    ("Step size equals inverse curvature", "N5"),
])
def test_each_rule_catches_its_shape(name, rule):
    assert rule in _ids(name)


def test_evidence_names_all_fail():
    for name in EVIDENCE:
        assert name_problems(name), name
    assert _ids(EVIDENCE[0]) >= {"N2", "N3", "N4"}
    assert _ids(EVIDENCE[1]) >= {"N2", "N3", "N5"}
    assert _ids(EVIDENCE[2]) >= {"N2", "N3", "N4"}


def test_every_rule_is_a_fail():
    for name in [*EVIDENCE, "", "Gradient descent converges"]:
        assert all(r.severity == FAIL for r in name_problems(name))


def test_check_names_reports_the_offending_name():
    report = check_names(["softmax", EVIDENCE[0]])
    assert not report.passed
    assert report.rubric == "concept_names"
    assert {"N2", "N3", "N4"} <= set(report.failed_ids)
    assert all("Gradient of the cost" in r.message for r in report.failures)
    assert check_names(["softmax", "L2 norm"]).passed


# ── Repair ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (EVIDENCE[0], "Gradient of the cost"),
    (EVIDENCE[1], "Least-squares cost"),
    (EVIDENCE[2], "Stability threshold"),
    ("Least-squares cost is convex", "Least-squares cost"),
    ("learning rate α", "learning rate"),
    ("O(n log n) sorting", "sorting"),
    ("Notation (θ)", "Notation"),
    ("  Momentum — damps oscillation ", "Momentum"),
    ("convergence rate of gradient descent on strongly convex quadratic objectives",
     "convergence rate of gradient descent"),
    ("Singular value decomposition of the design matrix for least squares problems",
     "Singular value decomposition of the design matrix"),
])
def test_repair_examples(raw, expected):
    assert repair_name(raw, fallback="Concept 1") == expected


@pytest.mark.parametrize("raw", ["∇J(θ)=Xᵀ(Xθ−y)", "", None, "=", "1 / L"])
def test_repair_falls_back_when_nothing_is_left(raw):
    assert repair_name(raw, fallback="Concept 3") == "Concept 3"


@pytest.mark.parametrize("raw", [
    *EVIDENCE, "a " * 40, "x" * 200, "Foo: bar", "is is is", "(∇)", "A — B — C", "1 / L",
    "Big-O: f(n) ≤ c·g(n) for all n ≥ n₀", "word " + "ᵀ" * 5, "Notation (θ)", "—", ":",
])
def test_repaired_names_always_pass(raw):
    assert name_problems(repair_name(raw, fallback="Concept 1")) == []


def test_passing_names_are_untouched():
    for name in ["Causal Self-Attention", "L2 norm", "Big-O", "Attention (transformers)"]:
        assert repair_name(name, fallback="x") == name


def test_word_cap_is_the_documented_one():
    assert MAX_NAME_WORDS == 7
    assert MAX_NAME_CHARS == 60


def test_repair_names_renames_consistently_across_the_prerequisite_map():
    key = ["Batch gradient descent update", EVIDENCE[0], EVIDENCE[1]]
    prereq = {
        EVIDENCE[0]: [EVIDENCE[1], "Matrix calculus: d(xᵀAx)/dx = 2Ax"],
        "batch gradient descent update": [EVIDENCE[0], "1-D minimization along a direction"],
    }
    fix = repair_names(key, prereq)
    assert fix.key_concepts == ["Batch gradient descent update", "Gradient of the cost",
                                "Least-squares cost"]
    assert fix.prerequisite_map == {
        "Gradient of the cost": ["Least-squares cost", "Matrix calculus"],
        # a case variant of a key concept maps onto that key concept's name
        "Batch gradient descent update": ["Gradient of the cost",
                                          "1-D minimization along a direction"],
    }
    assert fix.renamed[EVIDENCE[0]] == "Gradient of the cost"
    assert "Batch gradient descent update" not in fix.renamed
    assert not fix.report.passed and fix.changed


def test_repair_names_keeps_distinct_concepts_distinct():
    key = ["Gradient: the form averaged over samples", "Gradient: the form summed over samples",
           "Gradient"]
    fix = repair_names(key, {})
    assert len({n.casefold() for n in fix.key_concepts}) == 3
    assert fix.key_concepts[2] == "Gradient"  # a passing name keeps its name
    assert all(name_problems(n) == [] for n in fix.key_concepts)


def test_repair_names_noop_on_clean_foundation():
    fix = repair_names(["self-attention", "softmax"], {"self-attention": ["softmax"]})
    assert not fix.changed and fix.renamed == {}
    assert fix.key_concepts == ["self-attention", "softmax"]
    assert fix.prerequisite_map == {"self-attention": ["softmax"]}


def test_repair_names_tolerates_junk_shapes():
    fix = repair_names(["ok name", 7, None], {"ok name": "not a list", 3: ["x"]})
    assert all(isinstance(n, str) and name_problems(n) == [] for n in fix.key_concepts)
    assert all(isinstance(k, str) for k in fix.prerequisite_map)
    for values in fix.prerequisite_map.values():
        assert isinstance(values, list) and all(isinstance(v, str) for v in values)


def test_summary_lists_input_and_output():
    fix = repair_names([EVIDENCE[0]], {})
    text = fix.summary()
    assert text.startswith("WARN ")
    assert "N3" in text and "Gradient of the cost" in text
