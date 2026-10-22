"""grade_request / run_grader: the grader call grade_concept makes, as a reusable unit.

grade_concept (and so the paper-probe and roleplay graders) and the grading eval
(evals/grading) all go through these two functions, so the eval measures the prompt and the
checks the app runs, not a copy of them.
"""

import json

from adaptive_academy.engine.assess import build_grade_prompt, grade_request, run_grader
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.prompts import grade_prompt


def _answer(**overrides) -> LLMResponse:
    body = {"score": 0.9, "mechanism_present": True, "verdict": "ok", "gaps": [],
            "missing_required": [], "misconceptions_committed": []}
    body.update(overrides)
    return LLMResponse(text=json.dumps(body), stop_reason="end_turn")


def test_grade_request_dedupes_items_and_renders_the_app_prompt():
    req = grade_request("gradient descent", "self_explanation", ["explains the update"], "",
                        "theta <- theta - eta * grad", must_include=["a", " a ", "", "b"],
                        weak_signs=["m"])
    assert req.required == ("a", "b")
    assert req.misconceptions == ("m",)
    assert (req.system, req.user) == build_grade_prompt(
        "gradient descent", "self_explanation", ["explains the update"], "",
        "theta <- theta - eta * grad", required=["a", "b"], misconceptions=["m"])
    assert req.system == grade_prompt()


def test_run_grader_checks_the_answer_and_names_the_enforced_gaps(session):
    req = grade_request("gd", "self_explanation", ["c"], "", "answer",
                        must_include=["a", "b"], weak_signs=["m"])
    llm = ScriptedLLMClient([_answer(score=0.7, missing_required=["A"])])
    events: list[tuple[str, str]] = []
    run = run_grader(session, llm, req, emit=lambda k, d="": events.append((k, d)))
    assert run.rules_gaps == ["omitted required element: a"]
    assert run.grade.score == 0.7
    assert run.answer.attempts == 1
    assert events[0] == ("prompt", grade_prompt().tag)
    assert any(k == "grade:check" for k, _ in events)
    assert llm.calls[0]["system"] == req.system
    assert llm.calls[0]["messages"] == [{"role": "user", "content": req.user}]
