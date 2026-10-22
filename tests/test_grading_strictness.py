"""AA_GRADING_STRICTNESS: lenient | standard (default) | strict.

The level is rendered into GRADE as a short block of guidance (str.format, like every other
prompt), and named in the prompt tag ("assess.grade@v7:strict"), so grades made at different
levels can be told apart. It changes how the grader judges coverage and depth, never the caps
the code enforces (0.70 for a missing item, 0.50 for a misconception or no mechanism). An
unknown value grades at standard, and /api/setup says so.
"""

import json

import pytest
from sqlmodel import Session

from adaptive_academy.engine import assess
from adaptive_academy.engine.assess import (
    assess_concept, build_grade_prompt, current_grading_strictness, grade_request,
    grading_strictness_problem, run_grader,
)
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import Concept, KnowledgeEstimate, Rubric, Topic, Track
from adaptive_academy.prompts import (
    GRADE, GRADE_CORRECTION, GRADE_STRICTNESS, GRADING_STRICTNESS_LEVELS, Prompt, grade_prompt,
)
from adaptive_academy.settings import Settings, settings

LEVELS = ("lenient", "standard", "strict")


# ── Rendering ────────────────────────────────────────────────────────────────

def test_the_levels_are_lenient_standard_strict():
    assert GRADING_STRICTNESS_LEVELS == LEVELS
    assert set(GRADE_STRICTNESS) == set(LEVELS)


@pytest.mark.parametrize("level", LEVELS)
def test_each_level_renders_its_own_block_and_nothing_else(level):
    p = grade_prompt(level)
    assert isinstance(p, Prompt)
    assert GRADE_STRICTNESS[level] in p
    for other in set(LEVELS) - {level}:
        assert GRADE_STRICTNESS[other] not in p
    # Fully rendered: no placeholder left, and the JSON example's braces came out single.
    assert "{strictness" not in p and "{{" not in p and "}}" not in p
    assert '{"score": number' in p
    # The rest of GRADE is the same at every level.
    def generic(text: str, lvl: str) -> str:
        return (text.replace(GRADE_STRICTNESS[lvl], "<BLOCK>")
                .replace(f"GRADING STRICTNESS: {lvl}.", "GRADING STRICTNESS: <LEVEL>."))

    assert f"GRADING STRICTNESS: {level}." in p
    assert generic(p, level) == generic(grade_prompt("standard"), "standard")


def test_the_blocks_say_what_each_level_does():
    lenient, strict = (" ".join(GRADE_STRICTNESS[k].split()) for k in ("lenient", "strict"))
    assert "briefly or informally" in lenient
    assert "stated or clearly shown" in strict
    assert "explained, not just named" in strict
    # Strict still accepts an equivalent formulation: it asks for the idea, not the words.
    assert "equivalent" in strict


@pytest.mark.parametrize("level", LEVELS)
def test_every_level_keeps_the_caps_in_the_prompt(level):
    text = " ".join(grade_prompt(level).split())
    assert f"keep the score at or below {assess._OMISSION_CEIL:.2f}" in text
    assert f"keep the score at or below {assess._MISCONCEPTION_CEIL:.2f}" in text
    assert "the score MUST NOT exceed 0.50" in text


def test_the_tune_says_an_equivalent_formulation_covers_an_item():
    text = " ".join(grade_prompt("standard").split())
    assert "An equivalent formulation covers an item" in text
    assert "minimising the negative of a quantity covers maximising it" in text
    assert "a correct formula covers the statement it encodes" in text
    assert "a standard abbreviation covers the term" in text


def test_grade_is_v7_and_each_rendering_is_tagged_with_its_level():
    assert GRADE.version == 7
    for level in LEVELS:
        assert grade_prompt(level).tag == f"assess.grade@v7:{level}"
    assert grade_prompt().tag == "assess.grade@v7:standard"


def test_an_unknown_level_is_a_programming_error_in_grade_prompt():
    with pytest.raises(ValueError):
        grade_prompt("harsh")


# ── The setting ──────────────────────────────────────────────────────────────

def test_the_setting_defaults_to_standard(monkeypatch):
    monkeypatch.delenv("AA_GRADING_STRICTNESS", raising=False)
    assert Settings(_env_file=None).grading_strictness == "standard"
    monkeypatch.setenv("AA_GRADING_STRICTNESS", "  ")  # compose passes an unset var as ""
    assert Settings(_env_file=None).grading_strictness == "standard"
    monkeypatch.setenv("AA_GRADING_STRICTNESS", "strict")
    assert Settings(_env_file=None).grading_strictness == "strict"


@pytest.mark.parametrize("raw, level", [
    ("lenient", "lenient"), ("standard", "standard"), ("strict", "strict"),
    (" Strict ", "strict"), ("LENIENT", "lenient"), ("", "standard"),
])
def test_known_values_resolve_case_and_spaces_ignored(monkeypatch, raw, level):
    monkeypatch.setattr(settings, "grading_strictness", raw)
    assert current_grading_strictness() == level
    assert grading_strictness_problem() is None


@pytest.mark.parametrize("raw", ["harsh", "very strict", "1"])
def test_an_unknown_value_falls_back_to_standard_with_a_warning(monkeypatch, raw):
    monkeypatch.setattr(settings, "grading_strictness", raw)
    assert current_grading_strictness() == "standard"
    warning = grading_strictness_problem()
    assert warning is not None
    assert "AA_GRADING_STRICTNESS" in warning and f"'{raw}'" in warning
    assert "standard" in warning and "lenient" in warning and "strict" in warning


def test_the_warning_never_echoes_a_pasted_secret(monkeypatch):
    secret = "sk-ant-api03-SUPERSECRETVALUE"
    monkeypatch.setattr(settings, "grading_strictness", secret)
    warning = grading_strictness_problem()
    assert warning is not None and secret not in warning and "SUPERSECRET" not in warning


# ── The request and the tag ──────────────────────────────────────────────────

def _req(**kw):
    return grade_request("gd", "self_explanation", ["c"], "", "answer",
                         must_include=["a"], weak_signs=["m"], **kw)


def test_the_request_uses_the_configured_level(monkeypatch):
    monkeypatch.setattr(settings, "grading_strictness", "strict")
    req = _req()
    assert req.system == grade_prompt("strict")
    assert req.system.tag == "assess.grade@v7:strict"
    system, _ = build_grade_prompt("gd", "self_explanation", ["c"], "", "answer")
    assert system.tag == "assess.grade@v7:strict"


def test_an_explicit_level_overrides_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "grading_strictness", "strict")
    assert _req(strictness="lenient").system == grade_prompt("lenient")
    with pytest.raises(ValueError):
        _req(strictness="harsh")


def test_an_unknown_setting_grades_at_standard(monkeypatch):
    monkeypatch.setattr(settings, "grading_strictness", "harsh")
    assert _req().system.tag == "assess.grade@v7:standard"


def _answer(**overrides) -> LLMResponse:
    body = {"score": 0.9, "mechanism_present": True, "verdict": "ok", "gaps": [],
            "missing_required": [], "misconceptions_committed": []}
    body.update(overrides)
    return LLMResponse(text=json.dumps(body), stop_reason="end_turn")


@pytest.mark.parametrize("level", LEVELS)
def test_run_grader_traces_the_tag_with_its_level(session, monkeypatch, level):
    monkeypatch.setattr(settings, "grading_strictness", level)
    llm = ScriptedLLMClient([_answer()])
    events: list[tuple[str, str]] = []
    run_grader(session, llm, _req(), emit=lambda k, d="": events.append((k, d)))
    assert events[0] == ("prompt", f"assess.grade@v7:{level}")
    assert llm.calls[0]["system"] == grade_prompt(level)


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


def test_the_assessment_row_records_the_level(session, monkeypatch):
    monkeypatch.setattr(settings, "grading_strictness", "strict")
    concept = _concept(session)
    result = assess_concept(session, concept, "self_explanation", "x",
                            llm=ScriptedLLMClient([_answer()]))
    assert result.assessment.prompt_tag == "assess.grade@v7:strict"


def test_a_regenerated_grade_records_the_level_and_the_correction(session, monkeypatch):
    monkeypatch.setattr(settings, "grading_strictness", "lenient")
    concept = _concept(session)
    llm = ScriptedLLMClient([LLMResponse(text="not json", stop_reason="end_turn"), _answer()])
    result = assess_concept(session, concept, "self_explanation", "x", llm=llm)
    assert result.assessment.prompt_tag == \
        f"assess.grade@v7:lenient+{GRADE_CORRECTION.tag}"
    # The regeneration resends the same rendered system prompt.
    assert llm.calls[1]["system"] == grade_prompt("lenient")


# ── The caps do not move ─────────────────────────────────────────────────────

CAP_CASES = [
    # (grader answer, expected recorded score)
    (dict(score=0.9, missing_required=["learning rate"], gaps=["g"]), 0.70),
    (dict(score=0.9, misconceptions_committed=["always converges"], gaps=["g"]), 0.50),
    (dict(score=0.9, mechanism_present=False, gaps=["g"]), 0.50),
    (dict(score=0.9), 0.90),
]


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("answer, expected", CAP_CASES)
def test_the_caps_are_the_same_at_every_level(session, monkeypatch, level, answer, expected):
    monkeypatch.setattr(settings, "grading_strictness", level)
    concept = _concept(session, ["learning rate"], ["always converges"])
    result = assess_concept(session, concept, "self_explanation", "x",
                            llm=ScriptedLLMClient([_answer(**answer)]))
    assert result.assessment.score == expected
    assert (assess._OMISSION_CEIL, assess._MISCONCEPTION_CEIL, assess._NO_MECHANISM_CEIL) == \
        (0.70, 0.50, 0.50)
