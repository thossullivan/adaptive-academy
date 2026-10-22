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
    ("Least-squares cost is convex", "N5"), ("Gradient descent converges linearly", "N5"),
    ("Attention is all you need", "N5"),
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
    ("O(n log n) sorting", "Big-O sorting"),
    ("softmax(QK^T) attention", "softmax attention"),
    ("Gauss - Newton method: converges quadratically near the optimum", "Gauss-Newton method"),
    ("Learning rate: step size α", "Learning rate"),
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


# Review H1: real names that contain a claim-verb-looking word must pass untouched.
REAL_NAMES = [
    "K-means clustering", "k-means++ initialization", "Equal error rate", "IS-LM model",
    "Means-end analysis", "Causes of overfitting", "Ensures in Eiffel", "Bond yields",
    "Mini-batch k-means", "Fuzzy c-means", "What causes vanishing gradients",
    "What is a monad", "Gauss - Newton", "Gauss-Newton method", "Gauss - Newton method",
    "k means clustering", "Root causes of failure", "Bias-variance tradeoff",
    "Must-link constraints", "Gradient descent", "Learning rate decay",
]


# Review round 3: Title Case "Name - Claim" is a claim, not a hyphenated compound.
@pytest.mark.parametrize("name", [
    "Learning Rate - Too High Diverges", "Softmax - Outputs Sum To One",
    "Dropout - Prevents Co-Adaptation", "Bias-Variance Tradeoff - Why Simple Models Underfit",
    "Momentum - Faster Convergence",
])
def test_title_case_dash_claims_fail_n4(name):
    assert "N4" in _ids(name)
    assert name_problems(repair_name(name, fallback="Concept 1")) == []


# Review round 3: claim verbs that double as nouns are claims inside a clause.
@pytest.mark.parametrize("name", [
    "Convexity ensures a unique minimum", "High learning rate causes divergence",
    "Low bias means high variance", "Ridge yields a unique solution",
    "Least-squares cost, which is convex", "Softmax, which is differentiable",
    "Learning rate must be small", "Weights should be small",
    "Dropout prevents co-adaptation", "Gradient vanishes", "Training loss decreases",
    "Gradient converges",
])
def test_claims_fail_n5(name):
    assert "N5" in _ids(name)
    assert name_problems(repair_name(name, fallback="Concept 1")) == []


def test_claim_repairs_keep_the_subject():
    assert repair_name("High learning rate causes divergence", fallback="x") == \
        "High learning rate"
    assert repair_name("Gradient vanishes", fallback="x") == "Gradient"


@pytest.mark.parametrize("name", REAL_NAMES)
def test_real_names_pass_and_repair_leaves_them_whole(name):
    assert name_problems(name) == []
    assert repair_name(name, fallback="Concept 1") == name
    fix = repair_names([name], {})
    assert fix.key_concepts == [name] and not fix.report.failed_ids


def test_merge_never_stores_a_self_loop():
    fix = repair_names(["Learning rate", "Learning rate: step size α"],
                       {"Learning rate: step size α": ["Learning rate"]})
    assert fix.key_concepts == ["Learning rate"]
    assert fix.prerequisite_map == {"Learning rate": []}


@pytest.mark.parametrize("name", ["Is convex", "Bond yields", "Causes of overfitting"])
def test_a_verb_at_either_end_is_not_a_clause(name):
    assert "N5" not in _ids(name)


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


def test_two_failing_names_repaired_alike_stay_distinct():
    key = ["Gradient: the form averaged over samples", "Gradient: the form summed over samples"]
    fix = repair_names(key, {})
    assert fix.key_concepts == ["Gradient", "Gradient (2)"]
    assert all(name_problems(n) == [] for n in fix.key_concepts)


def test_failing_name_repaired_onto_a_passing_key_concept_merges():
    fix = repair_names(["Gradient: ∇J(θ)=Xᵀ(Xθ−y)", "Gradient"], {})
    assert fix.key_concepts == ["Gradient"]  # no visible "Gradient (2)"
    assert fix.renamed == {"Gradient: ∇J(θ)=Xᵀ(Xθ−y)": "Gradient"}


def test_failing_key_repaired_onto_a_map_only_name_merges_and_stays_load_bearing():
    from adaptive_academy.engine.curriculum import load_bearing_concepts

    fix = repair_names(["Learning rate: step size α", "Momentum"],
                       {"Momentum": ["Learning rate"]})
    assert fix.key_concepts == ["Learning rate", "Momentum"]
    assert fix.prerequisite_map == {"Momentum": ["Learning rate"]}
    assert load_bearing_concepts(fix.prerequisite_map, fix.key_concepts) == {"Learning rate"}


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


@pytest.mark.parametrize(("name", "expected"), [
    ("Gauss - Newton Method", "Gauss-Newton Method"),
    ("Kullback - Leibler Divergence", "Kullback-Leibler Divergence"),
    ("Cauchy - Schwarz Inequality", "Cauchy-Schwarz Inequality"),
    ("Levenberg - Marquardt Algorithm", "Levenberg-Marquardt Algorithm"),
    ("Generalized Gauss - Newton", "Generalized Gauss-Newton"),
    ("Damped Gauss - Newton method", "Damped Gauss-Newton method"),
])
def test_repair_keeps_named_compounds_whole(name, expected):
    # Final-review regression: the strict check fails these (the model is asked to fix
    # them), but repair must not cut them to the first surname.
    assert repair_name(name, fallback="Concept 1") == expected


@pytest.mark.parametrize("name", ["Softmax - Outputs Sum To One",
                                  "Learning Rate - Too High Diverges"])
def test_repair_still_drops_long_dash_claims(name):
    assert "-" not in repair_name(name, fallback="Concept 1").split()[0][1:]
