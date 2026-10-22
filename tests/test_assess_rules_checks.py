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
    "softmax(QK^T/sqrt(d))", "f(x)", "x theta", "a_i", "p(y|x)", "w <- w - lr * g",
    "dJ/dθ", "d_k", "X.T", "KL(p||q)", "1/m", "x/y",
])
def test_formula_like_items(item):
    assert is_formula_like(item)


@pytest.mark.parametrize("item", [
    "softmax", "subtract the max", "chain rule", "residual vector", "numerical stability",
    "derivative of the squared error via the chain rule", "p-value", "k-means",
    "self-attention", "Bayes' rule", "L2 regularization", "top-1 accuracy", "overflow",
    "residual (error) vector", "MSE", "ReLU",
    # Code identifiers and acronyms are words, matched exactly as tokens.
    "log_softmax", "__init__", "requires_grad", "np.dot", "TCP/IP", "C++", "KL", "L2",
    "A* search", "and/or", "GPT-3", "encoder/decoder",
    # Non-Latin scripts are words, including Greek-language prose.
    "градиентный спуск", "梯度下降", "الانحدار التدريجي", "η κλίση", "κλίση",
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


# ── Word matching is not fooled by near misses (review H2) ───────────────────

@pytest.mark.parametrize("response, item", [
    ("L1 regularization (lasso) shrinks weights to zero", "L2 regularization"),
    ("we report the top-5 error", "top-1 error"),
    ("GPT-3 is a decoder-only transformer", "GPT-2"),
    ("a 1D convolution over the sequence", "2D convolution"),
    ("we generate text by sampling while learning", "learning rate"),
    ("The error is not squared.", "squared error"),
    ("The loss isn't convex here.", "convex"),
    ("the error went up; much later, after many epochs, the gradient was squared", "squared error"),
])
def test_near_miss_is_still_a_hard_gap(response, item):
    assert apply_rules_checks(response, [item], []) == [f"omitted required element: {item}"]


@pytest.mark.parametrize("response, item", [
    ("L2 regularization adds a penalty", "L2 regularization"),
    ("the top-1 error drops", "top-1 error"),
    ("the learning rates were tuned", "learning rate"),
    ("errors get squared", "squared error"),
    ("the residuals shrink", "residual"),
    ("we normalized the activations", "normalize"),
    ("the loss is not only squared error but also a penalty", "squared"),
])
def test_word_item_matches_inflections_and_reordering(response, item):
    assert apply_rules_checks(response, [item], []) == []


# ── weak_signs match common inflections (review M1) ──────────────────────────

@pytest.mark.parametrize("response, sign", [
    ("SGD always converges to the global minimum", "always converge"),
    ("the model is overfitting the data", "overfit"),
    ("the network memorizes the training set", "memorize"),
    ("it simply memorized the answers", "memorize"),
])
def test_weak_sign_matches_inflected_forms(response, sign):
    assert apply_rules_checks(response, [], [sign]) == [
        f"contains likely misconception: {sign}"]


def test_negated_weak_sign_is_not_the_misconception():
    assert apply_rules_checks("SGD does not always converge", [], ["always converge"]) == []


# ── Non-Latin scripts keep the hard check (review M2) ────────────────────────

def test_cyrillic_word_item_missing_is_a_hard_gap():
    assert apply_rules_checks("мы используем обратное распространение", ["градиентный спуск"],
                              []) == ["omitted required element: градиентный спуск"]


def test_cyrillic_word_item_present_matches():
    assert apply_rules_checks("Градиентный спуск обновляет веса", ["градиентный спуск"],
                              []) == []


def test_cjk_word_item_present_and_missing():
    assert apply_rules_checks("我们使用梯度下降法训练模型", ["梯度下降"], []) == []
    assert apply_rules_checks("我们使用反向传播", ["梯度下降"], []) == [
        "omitted required element: 梯度下降"]


def test_arabic_weak_sign_is_a_hard_misconception():
    assert apply_rules_checks("النموذج يحفظ البيانات", [], ["يحفظ البيانات"]) == [
        "contains likely misconception: يحفظ البيانات"]


def test_greek_prose_is_matched_as_words_not_letter_names():
    assert apply_rules_checks("Η κλίση δείχνει προς τα πάνω", ["κλίση"], []) == []
    assert apply_rules_checks("Η παράγωγος", ["κλίση"], []) == [
        "omitted required element: κλίση"]


# ── Identifiers and acronyms are exact tokens (review M3) ────────────────────

@pytest.mark.parametrize("response, item", [
    ("call np.dot on the matrices", "np.dot"),
    ("use F.log_softmax for stability", "log_softmax"),
    ("set requires_grad=True", "requires_grad"),
    ("the __init__ method builds layers", "__init__"),
    ("TCP/IP stacks", "TCP/IP"),
    ("written in C++", "C++"),
    ("the KL divergence", "KL"),
    ("A* search with an admissible heuristic", "A* search"),
])
def test_identifier_and_acronym_items_match_exactly(response, item):
    assert apply_rules_checks(response, [item], []) == []


@pytest.mark.parametrize("response, item", [
    ("take the dot product", "np.dot"),
    ("use softmax then log", "log_softmax"),
    ("written in C", "C++"),
    ("TCP handles retransmission", "TCP/IP"),
    ("the L1 penalty", "L2"),
])
def test_identifier_and_acronym_items_are_hard_gaps_when_missing(response, item):
    assert apply_rules_checks(response, [item], []) == [f"omitted required element: {item}"]
