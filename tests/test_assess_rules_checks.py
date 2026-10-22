"""Deterministic anchor checks (assess.check_anchor_terms / apply_rules_checks): confident
absence is a hard gap; everything uncertain goes to the grader.

No phrase matcher strict enough to stop wrong answers leaves correct ones alone, and vice
versa. So a WORD must_include item has three outcomes:
  - satisfied: its words occur (stems, joined/split compounds) in one sentence, un-negated;
  - hard gap ("omitted required element", caps the score): NONE of its content words occur
    anywhere in the answer;
  - uncertain: anything else (a near miss, a negation, words spread over sentences). The
    grader is told "POSSIBLY MISSING: <item>" and decides by meaning; the score is not capped.
A weak sign is hard ("contains likely misconception") only on a full, un-negated phrase match;
a negated or partial match is a "POSSIBLE MISCONCEPTION" hint to the grader. Formula-like items
are always left to the grader (other notation can be right), as EXPECTED FORMULAS.
"""

import json
from pathlib import Path

import pytest

from adaptive_academy.engine.assess import (
    apply_rules_checks, check_anchor_terms, is_formula_like, normalize_math, penalize_score,
)

GOLDEN = Path(__file__).parent / "golden" / "rules_checks"


def _outcome(response: str, item: str) -> str:
    """satisfied | hard | uncertain, for one word must_include item."""
    assert not is_formula_like(item), item
    result = check_anchor_terms(response, [item], [])
    if result.gaps == [f"omitted required element: {item}"]:
        assert result.possibly_missing == []
        return "hard"
    assert result.gaps == []
    if result.possibly_missing == [item]:
        return "uncertain"
    assert result.possibly_missing == []
    return "satisfied"


def _sign(response: str, sign: str) -> str:
    """hard | soft | none, for one word weak sign."""
    result = check_anchor_terms(response, [], [sign])
    if result.gaps == [f"contains likely misconception: {sign}"]:
        assert result.possible_misconceptions == []
        return "hard"
    assert result.gaps == []
    if result.possible_misconceptions == [sign]:
        return "soft"
    assert result.possible_misconceptions == []
    return "none"


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


# ── Satisfied: correct answers the matcher must not miss ─────────────────────

@pytest.mark.parametrize("response, item", [
    # Markdown emphasis and code spans.
    ("We minimise it with **gradient descent**.", "gradient descent"),
    ("Scale the step by the *learning rate*.", "learning rate"),
    ("Scale the step by the _learning rate_.", "learning rate"),
    ("Each step uses ***momentum***.", "momentum"),
    ("Call `np.dot` on the matrices.", "np.dot"),
    ("Use `log_softmax` for stability.", "log_softmax"),
    # Possessives, either side.
    ("By Jensen's inequality the bound holds.", "Jensen inequality"),
    ("By the Jensen inequality the bound holds.", "Jensen's inequality"),
    ("Newtons method uses the Hessian.", "Newton's method"),
    ("Newton's method uses the Hessian.", "Newtons method"),
    ("Bayes' rule inverts the conditional.", "Bayes rule"),
    # Closed, hyphenated and open compounds, either side.
    ("Pretraining on a large corpus comes first.", "pre-training"),
    ("Pre-training on a large corpus comes first.", "pretraining"),
    ("Pre training on a large corpus comes first.", "pretraining"),
    ("The model was pretrained on text.", "pre-training"),
    ("ReLU makes the network nonlinear.", "non-linear"),
    ("ReLU makes the network non-linear.", "nonlinear"),
    ("It is a bias-variance tradeoff.", "trade-off"),
    ("It is a bias-variance trade-off.", "tradeoff"),
    ("Hold out part of the dataset.", "data set"),
    ("Hold out part of the data set.", "dataset"),
    ("A 1-D convolution slides along time.", "1D convolution"),
    ("GPT2 is decoder-only.", "GPT-2"),
    # Contractions don't break words ("can't" is "can not", not "ca not").
    ("The step can't overshoot when it's small.", "can not overshoot"),
    ("We won't converge without it.", "will not converge"),
    # Paraphrase: all content words in one sentence, any order or distance.
    ("The error between prediction and target is squared.", "squared error"),
    ("the error, squared, is minimised", "squared error"),
    ("Apply the CHAIN-RULE to the loss.", "chain rule"),
    ("by the chain\nrule, the derivative is...", "chain rule"),
    ("Chain   Rule!", "chain rule"),
    ("the rule here is the chain rule", "chain rule"),
    ("the learning rate η sets the step", "learning rate"),
    # Inflections either way, including inflected to inflected.
    ("L2 regularization adds a penalty", "L2 regularization"),
    ("the top-1 error drops", "top-1 error"),
    ("the learning rates were tuned", "learning rate"),
    ("errors get squared", "squared error"),
    ("the residuals shrink", "residual"),
    ("we normalized the activations", "normalize"),
    ("it converged after it had converges", "converging"),
    ("the loss is not only squared error but also a penalty", "squared"),
    # An item that states a negation is matched with it.
    ("We draw a minibatch by sampling without replacement.", "sampling without replacement"),
    ("Logistic regression has no closed-form solution.", "no closed-form solution"),
    ("There's no closed form solution, so we iterate.", "no closed-form solution"),
    # Identifiers and acronyms, exact.
    ("call np.dot on the matrices", "np.dot"),
    ("use F.log_softmax for stability", "log_softmax"),
    ("set requires_grad=True", "requires_grad"),
    ("the __init__ method builds layers", "__init__"),
    ("TCP/IP stacks", "TCP/IP"),
    ("written in C++", "C++"),
    ("the KL divergence", "KL"),
    ("A* search with an admissible heuristic", "A* search"),
    ("We report AUC-ROC on the test split.", "AUC-ROC"),
    ("Weight terms by TF-IDF.", "TF-IDF"),
    # Other scripts.
    ("Градиентный спуск обновляет веса", "градиентный спуск"),
    ("我们使用梯度下降法训练模型", "梯度下降"),
    ("Η κλίση δείχνει προς τα πάνω", "κλίση"),
])
def test_correct_answers_satisfy_the_item(response, item):
    assert _outcome(response, item) == "satisfied"


# ── Uncertain: near misses, negations and spread-out words go to the grader ──

@pytest.mark.parametrize("response, item", [
    # Near misses: a shared word is there, the exact token is not.
    ("L1 regularization (lasso) shrinks weights to zero", "L2 regularization"),
    ("we report the top-5 error", "top-1 error"),
    ("GPT-3 is a decoder-only transformer", "GPT-2"),
    ("a 1D convolution over the sequence", "2D convolution"),
    ("we generate text by sampling while learning", "learning rate"),
    ("take the dot product", "np.dot"),
    ("use softmax then log", "log_softmax"),
    ("TCP handles retransmission", "TCP/IP"),
    # Negations: present but denied, or present in a correct negative statement.
    ("The error is not squared.", "squared error"),
    ("The loss isn't convex here.", "convex"),
    ("The loss is not a convex function.", "convex function"),
    ("Elastic net uses neither L1 nor L2 regularization alone.", "L2 regularization"),
    ("Logistic regression has no closed-form solution.", "closed-form solution"),
    ("We sample without replacement.", "replacement"),
    # Words in different sentences.
    ("the error went up; much later, after many epochs, the gradient was squared",
     "squared error"),
    ("We use the chain. The rule is simple.", "chain rule"),
])
def test_uncertain_items_are_left_to_the_grader(response, item):
    assert _outcome(response, item) == "uncertain"


def test_uncertain_item_is_not_capped():
    result = check_anchor_terms("L1 regularization shrinks weights", ["L2 regularization"], [])
    assert result.gaps == [] and result.possibly_missing == ["L2 regularization"]
    assert result.left_to_grader == ["L2 regularization"]
    assert penalize_score(0.9, result.gaps) == 0.9


# ── Hard: confident absence ──────────────────────────────────────────────────

@pytest.mark.parametrize("response, item", [
    ("the gradient points uphill", "residual"),
    ("the gradient points uphill", "chain rule"),
    ("We take the derivative of each layer in turn.", "chain rule"),
    ("the error is minimised", "residual vector"),
    ("the L1 penalty", "L2"),
    ("written in C", "C++"),
    ("we generate text", "learning rate"),
    ("мы используем обратное распространение", "градиентный спуск"),
    ("我们使用反向传播", "梯度下降"),
    ("Η παράγωγος", "κλίση"),
])
def test_items_with_no_content_word_present_are_hard_gaps(response, item):
    assert _outcome(response, item) == "hard"


def test_hard_gaps_cap_the_score():
    gaps = apply_rules_checks("the gradient points uphill", ["chain rule", "residual"], [])
    assert gaps == ["omitted required element: chain rule",
                    "omitted required element: residual"]
    assert penalize_score(0.9, gaps) == 0.7


def test_word_in_an_empty_answer_is_a_hard_gap():
    assert apply_rules_checks("", ["chain rule"], []) == ["omitted required element: chain rule"]


# ── weak_signs: hard on a full, un-negated phrase; otherwise a hint ──────────

@pytest.mark.parametrize("response, sign", [
    ("Attention is MEMORY, basically.", "attention is memory"),
    ("SGD always converges to the global minimum", "always converge"),
    ("the model is overfitting the data", "overfit"),
    ("the network memorizes the training set", "memorize"),
    ("it simply memorized the answers", "memorize"),
    ("attention uses softmax; it just picks the max", "it just picks the max"),
    ("the model **over-fits** the data", "overfit"),
    ("النموذج يحفظ البيانات", "يحفظ البيانات"),
])
def test_full_weak_sign_is_a_hard_misconception(response, sign):
    assert _sign(response, sign) == "hard"


@pytest.mark.parametrize("response, sign", [
    # Negated: the answer denies it.
    ("SGD does not always converge", "always converge"),
    ("SGD doesn't always converge", "always converge"),
    ("the model is not overfitting", "overfit"),
    ("it never memorizes the data", "memorize"),
    # Partial: the sign's words are in one sentence, not as the phrase.
    ("attention is not memory", "attention is memory"),
    ("SGD will always, in practice, converge", "always converge"),
])
def test_negated_or_partial_weak_sign_is_a_hint(response, sign):
    assert _sign(response, sign) == "soft"


@pytest.mark.parametrize("response, sign", [
    ("the process is memoryless", "memory"),
    ("attention weights sum to one", "attention is memory"),
    ("SGD always moves downhill. It may converge.", "always converge"),
])
def test_absent_weak_sign_is_nothing(response, sign):
    assert _sign(response, sign) == "none"


def test_formula_weak_sign_is_left_to_the_grader():
    # A formula fragment can sit inside a correct expression ("Xθ" inside "Xᵀ(Xθ − y)"), so a
    # literal hit is not evidence of the misconception: the grader judges it.
    result = check_anchor_terms("the gradient is Xᵀ(Xθ − y)", [], ["Xθ"])
    assert result.gaps == []
    assert result.possible_misconceptions == ["Xθ"]
    assert result.left_to_grader == ["Xθ"]


def test_absent_formula_weak_sign_is_not_noted():
    assert check_anchor_terms("softmax over scores", [], ["Xθ"]).left_to_grader == []


# ── Formula items keep going to the grader ───────────────────────────────────

def test_ascii_answer_matches_unicode_formula_item():
    # Same formula, same variable names, different typing: matched, so not even a soft note.
    result = check_anchor_terms("the gradient is X^T (X theta - y)", ["Xᵀ(Xθ − y)"], [])
    assert result.gaps == [] and result.left_to_grader == []
    assert result.formulas == ["Xᵀ(Xθ − y)"]


def test_unicode_answer_matches_ascii_formula_item():
    result = check_anchor_terms("it equals Xᵀ(Xθ − y)", ["X^T(X theta - y)"], [])
    assert result.gaps == [] and result.left_to_grader == []


def test_unmatched_formula_item_is_a_soft_note_not_a_hard_gap():
    result = check_anchor_terms("attention uses softmax", ["softmax", "QK^T"], [])
    assert result.gaps == []
    assert result.formulas == ["QK^T"]
    assert result.possibly_missing == []
    assert result.left_to_grader == ["QK^T"]
    assert penalize_score(0.9, result.gaps) == 0.9


def test_mixed_rubric_sorts_items_into_the_three_outcomes():
    result = check_anchor_terms(
        "attention uses softmax over scores; it just picks the max. L1 scaling helps.",
        ["softmax", "QK^T", "weighted sum of values", "L2 scaling"],
        ["it just picks the max", "attention is memory"])
    assert result.gaps == ["omitted required element: weighted sum of values",
                           "contains likely misconception: it just picks the max"]
    assert result.formulas == ["QK^T"]
    assert result.possibly_missing == ["L2 scaling"]
    assert result.possible_misconceptions == []


# ── The formula-like heuristic ───────────────────────────────────────────────

@pytest.mark.parametrize("item", [
    "Xᵀ(Xθ − y)", "(1/m)Xᵀ(Xθ − y)", "residual r = Xθ − y", "∇J(θ)", "½‖Xθ − y‖²",
    "QK^T", "scale by sqrt(d)", "O(n^2)", "x - y", "x-y", "learning rate η", "√d_k",
    "softmax(QK^T/sqrt(d))", "f(x)", "x theta", "a_i", "p(y|x)", "w <- w - lr * g",
    "dJ/dθ", "d_k", "X.T", "KL(p||q)", "1/m", "x/y",
    # Leibniz derivatives are notation, not word/word.
    "dL/dw", "dy/dx", "the gradient dL/dW", "dz/dx1",
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
    # Hyphenated acronyms are words, not a minus between symbols.
    "AUC-ROC", "TF-IDF", "CNN-LSTM", "BERT-base", "seq2seq",
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
