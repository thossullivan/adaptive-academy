import json
from datetime import datetime, timedelta, timezone

from adaptive_academy.engine.decay import (
    due_decay_checks,
    grade_decay_check,
    schedule_decay_check,
)
from adaptive_academy.engine.productive_failure import (
    consolidate,
    parse_consolidation_json,
    parse_problem_json,
)
from adaptive_academy.engine.teach import grade_teaching, has_taught, parse_teaching_json
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment,
    Concept,
    RecallPrompt,
    Topic,
    Track,
)
from adaptive_academy.prompts import GRADE, PF_CONSOLIDATE, TEACH


class FixedLLM:
    """Returns a fixed JSON string for any call."""

    def __init__(self, text: str):
        self._text = text

    def complete(self, system, messages, tools):  # noqa: ANN001
        return LLMResponse(text=self._text, tool_calls=[])


class RouterLLM:
    """Routes by system-prompt content — needed for the recall path (rubric + grade calls)."""

    def complete(self, system, messages, tools):  # noqa: ANN001
        s = system.lower()
        if "grading rubric" in s:
            text = json.dumps({"criteria": ["c"], "must_include": [], "strong_signs": [],
                               "weak_signs": [], "source_refs": []})
        elif "skeptical grader" in s:
            text = json.dumps({"score": 0.5, "verdict": "partial recall", "gaps": [],
                               "confidence_actual": 0.5,
                               "missing_required": [], "misconceptions_committed": []})
        else:
            text = "{}"
        return LLMResponse(text=text, tool_calls=[])


def _seed_concept(session, name="self-attention"):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.refresh(topic)
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    session.refresh(track)
    concept = Concept(track_id=track.id, name=name, is_load_bearing=True)
    session.add(concept)
    session.commit()
    session.refresh(concept)
    return topic, concept


# ─── Decay ───────────────────────────────────────────────────────────────────

def test_schedule_decay_check_is_idempotent(session):
    _, concept = _seed_concept(session)
    p1 = schedule_decay_check(session, concept.id, days=3)
    p2 = schedule_decay_check(session, concept.id, days=5)
    # Same single active prompt, due date re-armed.
    all_prompts = session.exec(RecallPrompt.__table__.select()).all()
    assert len(all_prompts) == 1
    assert p1.id == p2.id


def test_due_decay_checks_returns_only_arrived(session):
    topic, concept = _seed_concept(session)
    p = schedule_decay_check(session, concept.id, days=3)
    assert due_decay_checks(session, topic.id) == []  # not due yet
    p.due_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    session.add(p)
    session.commit()
    due = due_decay_checks(session, topic.id)
    assert len(due) == 1 and due[0].id == p.id


def test_grade_decay_check_computes_decay_and_reschedules(session):
    topic, concept = _seed_concept(session)
    # Prior understanding was strong (0.8); recall will score 0.5 → decayed.
    session.add(Assessment(concept_id=concept.id, kind="self_explanation", prompt="p", score=0.8))
    session.commit()
    prompt = schedule_decay_check(session, concept.id, days=0)

    result = grade_decay_check(session, prompt.id, "from memory…", llm=RouterLLM())
    assert result.recall_score == 0.5
    assert result.baseline_score == 0.8
    assert result.decay_delta == -0.3
    assert result.held is False
    # Rescheduled sooner (decayed → 2 days) and marked.
    session.refresh(prompt)
    assert prompt.last_result == "decayed"
    assert result.assessment.kind == "recall"
    # Recall is graded by assess_concept's GRADE, not the DECAY_RECALL probe text.
    assert result.assessment.prompt_tag == GRADE.tag


# ─── Productive Failure ──────────────────────────────────────────────────────

def test_parse_problem_and_consolidation_json():
    assert parse_problem_json('{"problem": "derive softmax grad"}') == "derive softmax grad"
    canonical, feedback, score = parse_consolidation_json(
        '```json\n{"canonical": "use chain rule", "feedback": "good start", "score": 0.7}\n```')
    assert canonical == "use chain rule" and feedback == "good start" and score == 0.7


def test_pf_generate_prompt_carries_prior_knowledge_level():
    from adaptive_academy.engine.productive_failure import build_generate_prompt

    _, user = build_generate_prompt("softmax", None, "low")
    assert "LEARNER PRIOR-KNOWLEDGE LEVEL: low" in user


def test_consolidate_persists_productive_failure_assessment(session):
    _, concept = _seed_concept(session)
    fake = FixedLLM(json.dumps({"canonical": "C", "feedback": "F", "score": 0.6}))
    result = consolidate(session, concept, "the problem", "my attempt", llm=fake)
    assert result.score == 0.6 and result.canonical == "C"
    assert result.assessment.kind == "productive_failure"
    assert result.assessment.prompt == "the problem"
    assert result.assessment.response == "my attempt"
    # The consolidation prompt graded the attempt (PF_GENERATE only wrote the problem).
    assert result.assessment.prompt_tag == PF_CONSOLIDATE.tag


# ─── Teach-It ────────────────────────────────────────────────────────────────

def test_parse_teaching_json():
    score, feedback, strengths, gaps = parse_teaching_json(
        '{"score": 0.8, "feedback": "clear", "strengths": ["a"], "gaps": ["b"]}')
    assert score == 0.8 and strengths == ["a"] and gaps == ["b"]


def test_grade_teaching_persists_and_has_taught(session):
    _, concept = _seed_concept(session)
    assert has_taught(session, concept.id) is False
    fake = FixedLLM(json.dumps({"score": 0.75, "feedback": "solid", "strengths": ["clear"],
                                "gaps": ["edge cases"]}))
    result = grade_teaching(session, concept, "Here is how attention works…", llm=fake)
    assert result.score == 0.75 and result.gaps == ["edge cases"]
    assert result.assessment.kind == "teach"
    assert result.assessment.prompt_tag == TEACH.tag
    assert has_taught(session, concept.id) is True
