"""Rubric items: the grader judges, the code enforces.

No string matching decides a cap. Four review rounds showed a word matcher cannot judge
meaning: every hard cap it applied hit correct answers ("regularised" for "regularization",
"GD" for "gradient descent", "step size" for "learning rate") or answers that name a
misconception to reject it ("A common misconception is that GD always converges").

So every must_include item (and source-quiz key point), word or formula, goes to the grader as
a REQUIRED ELEMENT, and every weak sign as a KNOWN MISCONCEPTION. The grader names the ones the
answer misses or commits (missing_required / misconceptions_committed, each exactly an item as
given; output_checks G11-G14), and the code applies the caps: 0.70 and "omitted required
element: <item>" for a missing one, 0.50 and "contains likely misconception: <item>" for a
committed one.
"""

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from adaptive_academy.engine.assess import assess_concept, build_grade_prompt
from adaptive_academy.engine.output_checks import GradeCheckError
from adaptive_academy.llm.errors import classify_llm_error
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent, Assessment, Concept, KnowledgeEstimate, ReferenceAnchor, Rubric, SourceDoc,
    Topic, Track,
)
from adaptive_academy.prompts import grade_prompt, GRADE_CORRECTION

GOLDEN = Path(__file__).parent / "golden" / "rubric_items"


def _concept(session: Session, must_include=(), weak_signs=()) -> Concept:
    topic = Topic(title="Optimisation")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="gradient descent")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="medium", confidence=0.5))
    session.add(Rubric(concept_id=concept.id, criteria=["explains the update"],
                       must_include=list(must_include), weak_signs=list(weak_signs)))
    session.commit()
    return concept


def _grade(score=0.9, missing=(), committed=(), gaps=(), **extra) -> LLMResponse:
    return LLMResponse(text=json.dumps({
        "score": score, "mechanism_present": True, "verdict": "v",
        "gaps": list(gaps), "missing_required": list(missing),
        "misconceptions_committed": list(committed), **extra}))


def _assess(session, concept, response, *grades, kind="self_explanation"):
    llm = ScriptedLLMClient(list(grades))
    result = assess_concept(session, concept, kind, response, llm=llm)
    return result.assessment, llm


def _user(llm, call=0) -> str:
    return llm.calls[call]["messages"][0]["content"]


# ── Correct answers the old matcher capped: the grader credits them, no cap ──

CORRECT_ANSWERS = [
    # (response, must_include, weak_signs)
    ("We regularised the weights with an L2 penalty.", ["regularization"], []),
    ("Convexity of the loss means every local minimum is global.", ["convex"], []),
    ("Multiply the two matrices, then add the bias.", ["matrix"], []),
    ("Backprop computes every partial derivative in one backward pass.",
     ["backpropagation"], []),
    ("GD takes a step against the gradient each iteration.", ["gradient descent"], []),
    ("The step size scales each update.", ["learning rate"], []),
    ("We normalise the inputs and optimise the centred loss.",
     ["normalize", "optimize", "centered"], []),
    ("A common misconception is that GD always converges; it can diverge.",
     ["diverge"], ["always converges"]),
    ("Does gradient descent always converge? No: with too large a step it diverges.",
     ["diverge"], ["always converges"]),
    ("It's a fallacy that correlation implies causation.", [],
     ["correlation implies causation"]),
    ("For least squares the gradient is (2/n) X^T (Xw - y)",
     ["Xᵀ(Xθ − y)", "½‖Xθ − y‖²"], []),
]


@pytest.mark.parametrize("response, must_include, weak_signs", CORRECT_ANSWERS)
def test_correct_answer_the_grader_credits_is_not_capped(session, response, must_include,
                                                          weak_signs):
    concept = _concept(session, must_include, weak_signs)
    a, llm = _assess(session, concept, response, _grade(0.9))
    assert a.score == 0.9
    assert not any(g.startswith(("omitted required element", "contains likely misconception"))
                   for g in a.gaps)
    user = _user(llm)
    for item in must_include:
        assert f"- {item}" in user.split("REQUIRED ELEMENTS:")[1].split("<<<RESPONSE>>>")[0]
    for sign in weak_signs:
        assert f"- {sign}" in user.split("KNOWN MISCONCEPTIONS:")[1].split("<<<RESPONSE>>>")[0]


# ── The code enforces what the grader names ──────────────────────────────────

def test_missing_required_element_caps_at_070_with_the_gap(session):
    concept = _concept(session, ["learning rate", "chain rule"])
    a, _ = _assess(session, concept, "GD steps downhill.", _grade(0.9, missing=["chain rule"]))
    assert a.score == 0.7
    assert a.gaps == ["omitted required element: chain rule"]
    est = session.exec(select(KnowledgeEstimate)).one()
    assert est.level == "medium" and est.confidence == 0.7
    rules = session.exec(select(AgentEvent).where(AgentEvent.kind == "assess:rules")).one()
    assert rules.detail == "1 hard gap(s)"


def test_named_items_are_recorded_as_given_not_as_the_grader_spelled_them(session):
    concept = _concept(session, ["Learning rate"], ["always converges"])
    a, _ = _assess(session, concept, "x",
                   _grade(0.9, missing=["  learning RATE "], committed=["ALWAYS converges"],
                          gaps=["no update rule"]))
    assert a.gaps == ["no update rule", "omitted required element: Learning rate",
                      "contains likely misconception: always converges"]


def test_committed_misconception_caps_at_050_with_the_gap(session):
    concept = _concept(session, ["learning rate"], ["always converges"])
    a, _ = _assess(session, concept, "GD always converges, whatever the learning rate.",
                   _grade(0.9, committed=["always converges"]))
    assert a.score == 0.5
    assert a.gaps == ["contains likely misconception: always converges"]


def test_both_caps_take_the_lower(session):
    concept = _concept(session, ["learning rate"], ["always converges"])
    a, _ = _assess(session, concept, "GD always converges.",
                   _grade(0.9, missing=["learning rate"], committed=["always converges"]))
    assert a.score == 0.5
    assert a.gaps == ["omitted required element: learning rate",
                      "contains likely misconception: always converges"]


def test_a_score_below_the_cap_is_kept(session):
    concept = _concept(session, ["learning rate"])
    a, _ = _assess(session, concept, "It goes down.",
                   _grade(0.3, missing=["learning rate"], gaps=["no mechanism"]))
    assert a.score == 0.3


def test_an_item_named_twice_is_one_gap(session):
    concept = _concept(session, ["learning rate"])
    a, _ = _assess(session, concept, "x",
                   _grade(0.7, missing=["learning rate", "Learning Rate"], gaps=["g"]))
    assert a.gaps == ["g", "omitted required element: learning rate"]


# ── An unknown item is regenerated, then rejected ────────────────────────────

@pytest.mark.parametrize("field, rule", [("missing", "G13"), ("committed", "G14")])
def test_unknown_item_is_regenerated_with_its_rule_named(session, field, rule):
    concept = _concept(session, ["learning rate"], ["always converges"])
    bad = _grade(0.7, gaps=["g"], **{field: ["momentum"]})
    a, llm = _assess(session, concept, "x", bad, _grade(0.9))
    assert a.score == 0.9
    assert a.prompt_tag == f"{grade_prompt().tag}+{GRADE_CORRECTION.tag}"
    correction = llm.calls[1]["messages"][-1]["content"]
    assert f"- {rule}:" in correction and "momentum" in correction


@pytest.mark.parametrize("field, rule", [("missing", "G13"), ("committed", "G14")])
def test_unknown_item_twice_is_invalid_output_and_writes_nothing(session, field, rule):
    concept = _concept(session, ["learning rate"], ["always converges"])
    bad = _grade(0.7, gaps=["g"], **{field: ["momentum"]})
    with pytest.raises(GradeCheckError) as exc:
        _assess(session, concept, "x", bad, bad)
    assert exc.value.rule_ids == (rule,)
    assert classify_llm_error(exc.value) == "invalid_output"
    assert session.exec(select(Assessment)).first() is None
    assert session.exec(select(KnowledgeEstimate)).one().level == "medium"


def test_absent_rubric_fields_are_regenerated(session):
    concept = _concept(session, ["learning rate"])
    old_shape = LLMResponse(text=json.dumps(
        {"score": 0.9, "mechanism_present": True, "verdict": "v", "gaps": []}))
    a, llm = _assess(session, concept, "x", old_shape, _grade(0.9))
    correction = llm.calls[1]["messages"][-1]["content"]
    # Only the field for a non-empty list is required: no misconceptions were sent.
    assert "- G11:" in correction and "- G12:" not in correction
    assert a.score == 0.9


# ── What the grader is sent ──────────────────────────────────────────────────

def test_grade_prompt_lists_every_item_every_time():
    _, user = build_grade_prompt(
        "gd", "self_explanation", ["c"], "", "answer",
        required=["learning rate", "Xᵀ(Xθ − y)"], misconceptions=["always converges"])
    assert "REQUIRED ELEMENTS:\n- learning rate\n- Xᵀ(Xθ − y)" in user
    assert "KNOWN MISCONCEPTIONS:\n- always converges" in user
    assert user.index("KNOWN MISCONCEPTIONS") < user.index("<<<RESPONSE>>>")


def test_grade_prompt_says_none_when_there_are_no_items():
    _, user = build_grade_prompt("gd", "artifact_review", ["c"], "", "answer")
    assert "REQUIRED ELEMENTS: (none)" in user
    assert "KNOWN MISCONCEPTIONS: (none)" in user


def test_blank_and_duplicate_items_are_not_sent(session):
    concept = _concept(session, ["learning rate", " ", "learning rate"], ["", "always"])
    _, llm = _assess(session, concept, "x", _grade(0.9))
    user = _user(llm)
    assert user.count("- learning rate") == 1
    assert "KNOWN MISCONCEPTIONS:\n- always\n" in user


# ── Source quiz: key points are the required elements ────────────────────────

def _anchor(session) -> Concept:
    concept = _concept(session)
    src = SourceDoc(topic_id=1, title="s", url="u", status="accepted")
    session.add(src)
    session.commit()
    session.add(ReferenceAnchor(
        source_doc_id=src.id, concept_id=concept.id, question="Why subtract the max?",
        reference_answer="stability", key_points=["numerical stability", "softmax(x - max(x))"]))
    session.commit()
    return concept


def test_source_quiz_key_points_are_required_elements(session):
    concept = _anchor(session)
    a, llm = _assess(session, concept, "so exp doesn't overflow",
                     _grade(0.9, missing=["softmax(x - max(x))"]), kind="source_quiz")
    assert a.score == 0.7
    assert a.gaps == ["omitted required element: softmax(x - max(x))"]
    required = _user(llm).split("REQUIRED ELEMENTS:")[1].split("KNOWN MISCONCEPTIONS")[0]
    assert "- numerical stability" in required and "- softmax(x - max(x))" in required


# ── The live case ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.json")), ids=lambda p: p.stem)
def test_golden_rubric_items(session, path):
    case = json.loads(path.read_text())
    concept = _concept(session, case["must_include"], case["weak_signs"])
    a, llm = _assess(session, concept, case["response"],
                     LLMResponse(text=json.dumps(case["grader"])))
    assert a.score == case["final_score"]
    assert a.gaps == case["gaps"]
    required = _user(llm).split("REQUIRED ELEMENTS:")[1].split("KNOWN MISCONCEPTIONS")[0]
    assert all(f"- {item}" in required for item in case["must_include"])


def test_golden_rubric_items_exist():
    assert list(GOLDEN.glob("*.json"))


@pytest.mark.parametrize(("sent", "named"), [
    ("numerical stability.", "numerical stability"),
    ("Xᵀ(Xθ − y)", "Xᵀ(Xθ - y)"),
    ("chain rule", '"chain rule"'),
    ("- learning rate", "learning rate"),
    ("Chain rule", "• chain rule;"),
])
def test_a_tidied_copy_of_an_item_still_matches(sent, named):
    from adaptive_academy.engine.output_checks import match_items

    found, unknown = match_items([named], [sent])
    assert found == [sent] and unknown == []


def test_absent_fields_are_fine_when_nothing_was_sent():
    from adaptive_academy.engine.output_checks import GRADE_RUBRIC, CheckContext, check_output

    _, report = check_output(GRADE_RUBRIC, '{"score": 0.5, "verdict": "ok", "gaps": ["x"], '
                                           '"mechanism_present": true}', CheckContext())
    assert "G11" not in report.failed_ids and "G12" not in report.failed_ids
