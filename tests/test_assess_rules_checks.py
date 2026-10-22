"""Deterministic anchor checks (assess.apply_rules_checks / check_anchor_terms) are fair to
correct answers written in other notation.

A must_include or weak_signs item written as a formula (Unicode math, variable names, a
particular convention) can't be checked literally: a learner who types X^T for Xᵀ, w for θ, or
the MSE convention without ½ is still right. So both sides are normalised (Unicode math to
ASCII, case, whitespace, punctuation), and a formula-like item is left to the model grader as
a soft note instead of a hard gap that caps the score. Plain-word items keep the hard check.
"""

import json
from pathlib import Path

import pytest

from adaptive_academy.engine.assess import (
    apply_rules_checks, check_anchor_terms, is_formula_like, normalize_math, penalize_score,
)

GOLDEN = Path(__file__).parent / "golden" / "rules_checks"


# ── The live case ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.json")), ids=lambda p: p.stem)
def test_golden_rules_checks(path):
    case = json.loads(path.read_text())
    result = check_anchor_terms(case["response"], case["must_include"], case["weak_signs"])
    assert result.gaps == case["hard_gaps"]
    assert result.left_to_grader == case["left_to_grader"]
    assert apply_rules_checks(case["response"], case["must_include"],
                              case["weak_signs"]) == case["hard_gaps"]
    assert penalize_score(case["llm_score"], result.gaps) == case["final_score"]


def test_golden_rules_checks_exist():
    assert list(GOLDEN.glob("*.json"))


def test_live_gradient_case_has_no_omission_gap():
    gaps = apply_rules_checks(
        "For least squares the gradient is (2/n) X^T (Xw - y)",
        ["Xᵀ(Xθ − y)", "(1/m)Xᵀ(Xθ − y)", "residual r = Xθ − y", "∇J(θ)", "½‖Xθ − y‖²"], [])
    assert not any(g.startswith("omitted required element") for g in gaps)
    assert penalize_score(0.9, gaps) == 0.9


# ── The formula-like heuristic ───────────────────────────────────────────────

@pytest.mark.parametrize("item", [
    "Xᵀ(Xθ − y)", "(1/m)Xᵀ(Xθ − y)", "residual r = Xθ − y", "∇J(θ)", "½‖Xθ − y‖²",
    "QK^T", "scale by sqrt(d)", "O(n^2)", "x - y", "x-y", "learning rate η", "√d_k",
    "softmax(QK^T/sqrt(d))", "f(x)", "x theta", "KL", "a_i", "p(y|x)", "w <- w - lr * g",
    "dJ/dθ",
])
def test_formula_like_items(item):
    assert is_formula_like(item)


@pytest.mark.parametrize("item", [
    "softmax", "subtract the max", "chain rule", "residual vector", "numerical stability",
    "derivative of the squared error via the chain rule", "p-value", "k-means",
    "self-attention", "Bayes' rule", "L2 regularization", "top-1 accuracy", "overflow",
    "residual (error) vector", "MSE", "ReLU",
])
def test_word_items(item):
    assert not is_formula_like(item)


# ── Normalisation ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("unicode_form, ascii_form", [
    ("Xᵀ(Xθ − y)", "X^T(X theta - y)"),
    ("½‖Xθ − y‖²", "1/2 ||X theta - y||^2"),
    ("∇J(θ)", "grad J(theta)"),
    ("Θ", "theta"),
    ("x₁ + x²", "x_1 + x^2"),
    ("a × b", "a * b"),
])
def test_normalize_math_maps_unicode_to_ascii(unicode_form, ascii_form):
    def squash(s: str) -> str:
        return "".join(normalize_math(s).split())

    assert squash(unicode_form) == squash(ascii_form)


def test_ascii_answer_matches_unicode_formula_item():
    # Same formula, same variable names, different typing: matched, so not even a soft note.
    result = check_anchor_terms("the gradient is X^T (X theta - y)", ["Xᵀ(Xθ − y)"], [])
    assert result.gaps == [] and result.left_to_grader == []


def test_unicode_answer_matches_ascii_formula_item():
    result = check_anchor_terms("it equals Xᵀ(Xθ − y)", ["X^T(X theta - y)"], [])
    assert result.gaps == [] and result.left_to_grader == []


def test_unmatched_formula_item_is_a_soft_note_not_a_hard_gap():
    result = check_anchor_terms("attention uses softmax", ["softmax", "QK^T"], [])
    assert result.gaps == []
    assert result.left_to_grader == ["QK^T"]
    assert penalize_score(0.9, result.gaps) == 0.9


# ── Word items keep the hard check ───────────────────────────────────────────

def test_missing_word_item_is_still_a_hard_gap():
    gaps = apply_rules_checks("the gradient points uphill", ["chain rule", "residual"], [])
    assert gaps == ["omitted required element: chain rule",
                    "omitted required element: residual"]
    assert penalize_score(0.9, gaps) == 0.7


@pytest.mark.parametrize("response", [
    "Apply the CHAIN-RULE to the loss.",
    "by the chain\nrule, the derivative is...",
    "Chain   Rule!",
    "the rule here is the chain rule",
])
def test_word_item_matches_across_case_whitespace_and_punctuation(response):
    assert apply_rules_checks(response, ["chain rule"], []) == []


def test_word_item_matches_with_its_words_in_another_order():
    assert apply_rules_checks("the error, squared, is minimised", ["squared error"], []) == []


def test_word_item_missing_one_of_its_words_is_a_gap():
    assert apply_rules_checks("the error is minimised", ["squared error"], []) == [
        "omitted required element: squared error"]


def test_word_item_matches_a_unicode_spelled_answer():
    assert apply_rules_checks("the learning rate η sets the step", ["learning rate"], []) == []


# ── weak_signs ───────────────────────────────────────────────────────────────

def test_word_weak_sign_still_flags_a_misconception():
    gaps = apply_rules_checks("Attention is MEMORY, basically.", [], ["attention is memory"])
    assert gaps == ["contains likely misconception: attention is memory"]


def test_word_weak_sign_needs_whole_words():
    # "memory" inside "memoryless" is not the misconception.
    assert apply_rules_checks("the process is memoryless", [], ["memory"]) == []


def test_formula_weak_sign_is_left_to_the_grader():
    # A formula fragment can sit inside a correct expression ("Xθ" inside "Xᵀ(Xθ − y)"), so a
    # literal hit is not evidence of the misconception: the grader judges it.
    result = check_anchor_terms("the gradient is Xᵀ(Xθ − y)", [], ["Xθ"])
    assert result.gaps == []
    assert result.left_to_grader == ["Xθ"]


def test_absent_formula_weak_sign_is_not_noted():
    assert check_anchor_terms("softmax over scores", [], ["Xθ"]).left_to_grader == []
