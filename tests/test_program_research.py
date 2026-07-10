import json

import pytest
from sqlmodel import select

from adaptive_academy.engine.program_research import (
    PROGRAM_ANGLES,
    build_program_briefs,
    parse_program_obj,
    research_program,
)
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import AgentEvent, Milestone, Program, ProgramIntent

SYNTH = {
    "milestones": [
        {"title": "Math foundations", "success_criteria": "derive backprop cold",
         "depends_on": [],
         "topics": [{"title": "Linear algebra for DL", "why": "prereq",
                     "source_urls": ["https://example.com/la"]}]},
        {"title": "Architectures", "success_criteria": "implement a transformer unaided",
         "depends_on": [0, 5, 1],  # 5 is out of range, 1 is self → both dropped
         "topics": [{"title": "Attention from scratch", "why": "core"},
                    {"title": "Tokenization", "why": "core"}]},
    ]
}


def test_build_program_briefs_fills_goal_and_focus():
    briefs = build_program_briefs("PhD-level CS", "custom LLMs", 5)
    assert len(briefs) == 5
    assert [b.angle for b in briefs] == [a for a, _ in PROGRAM_ANGLES]
    assert "PhD-level CS" in briefs[0].query
    assert "custom LLMs" in briefs[0].query


def test_parse_program_obj_drops_invalid_depends_on():
    drafts = parse_program_obj(SYNTH)
    assert [d.title for d in drafts] == ["Math foundations", "Architectures"]
    assert drafts[1].depends_on == [0]  # forward/self refs dropped
    assert drafts[1].topics[0].title == "Attention from scratch"


def _program(session):
    p = Program(title="PhD prep", goal_statement="research-ready in custom LLMs")
    session.add(p)
    session.commit()
    intent = ProgramIntent(program_id=p.id, focus_area="custom LLMs",
                           prior_knowledge="MS-level math")
    session.add(intent)
    session.commit()
    return p, intent


def test_research_program_persists_milestones_and_links(session):
    p, intent = _program(session)
    researcher = ScriptedResearcherClient({
        "phd_curricula": [RawSource(title="MIT quals", url="https://mit.edu/q", tier=1)],
        "reading_lists": [RawSource(title="Papers", url="https://arxiv.org/x", tier=2)],
    })
    llm = ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))])
    result = research_program(session, p, intent, researcher=researcher, llm=llm)

    assert [m.title for m in result.milestones] == ["Math foundations", "Architectures"]
    assert result.milestones[0].gate_status == "open"
    assert result.milestones[1].depends_on == [result.milestones[0].id]
    assert len(result.links) == 3
    assert all(link.status == "proposed" and link.topic_id is None for link in result.links)
    assert result.links[0].sources == ["https://example.com/la"]
    kinds = {e.kind for e in result.events}
    assert "program_research:plan" in kinds
    assert "program_research:synth" in kinds
    assert all(e.program_id == p.id for e in result.events)


def test_research_program_survives_single_angle_failure(session):
    """Resilience: one angle errors but the others still return sources — synthesis
    proceeds grounded in the surviving angles' sources."""
    p, intent = _program(session)

    class FlakyResearcher:
        def search(self, brief):
            if brief.angle == "phd_curricula":
                raise RuntimeError("529")
            return [RawSource(title=f"{brief.angle} source",
                              url=f"https://e.com/{brief.angle}", tier=2)]

    llm = ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))])
    result = research_program(session, p, intent, researcher=FlakyResearcher(), llm=llm)
    kinds = [e.kind for e in result.events]
    assert "program_research:subagent_error" in kinds
    assert len(result.milestones) == 2  # synthesis still ran


def test_research_program_all_angles_failed_raises_and_persists_trace(session):
    """Regression (finding 2): if every angle errors, synthesis must not run (it would
    fabricate milestones from zero sources) and the ungrounded proposal must not be
    persisted — otherwise a subsequent research run is refused forever."""
    p, intent = _program(session)

    class AllFailResearcher:
        def search(self, brief):
            raise RuntimeError("529")

    llm = ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))])
    with pytest.raises(ValueError, match="no sources"):
        research_program(session, p, intent, researcher=AllFailResearcher(), llm=llm)

    # The LLM's synthesis payload was never consumed.
    assert llm.calls == []

    milestones_after = session.exec(
        select(Milestone).where(Milestone.program_id == p.id)
    ).all()
    assert milestones_after == []  # zero milestones persisted

    kinds = [e.kind for e in session.exec(
        select(AgentEvent).where(AgentEvent.program_id == p.id)
    ).all()]
    assert kinds.count("program_research:subagent_error") == len(PROGRAM_ANGLES)
    assert "program_research:synth" not in kinds
    assert "program_research:done" not in kinds

    # A subsequent research run is NOT blocked (no proposal was persisted).
    result = research_program(session, p, intent,
                              researcher=ScriptedResearcherClient({
                                  "phd_curricula": [RawSource(title="MIT quals",
                                                              url="https://mit.edu/q",
                                                              tier=1)],
                              }),
                              llm=ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))]))
    assert len(result.milestones) == 2


def test_research_program_all_angles_empty_raises_and_allows_retry(session):
    """All angles "succeed" but return zero sources (the historical silent-failure
    signature — e.g. truncated JSON from web-search fan-outs): synthesis must not run
    and no proposal is persisted, so a retry is not blocked."""
    p, intent = _program(session)

    llm = ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))])
    with pytest.raises(ValueError, match="no sources"):
        research_program(session, p, intent,
                         researcher=ScriptedResearcherClient({}),  # every angle → []
                         llm=llm)
    assert llm.calls == []  # synthesis never ran

    assert session.exec(
        select(Milestone).where(Milestone.program_id == p.id)
    ).all() == []  # zero milestones persisted

    # A subsequent research run is NOT blocked.
    result = research_program(session, p, intent,
                              researcher=ScriptedResearcherClient({
                                  "phd_curricula": [RawSource(title="MIT quals",
                                                              url="https://mit.edu/q",
                                                              tier=1)],
                              }),
                              llm=ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))]))
    assert len(result.milestones) == 2


def test_research_program_refuses_second_run(session):
    p, intent = _program(session)
    session.add(Milestone(program_id=p.id, title="existing", order_index=0))
    session.commit()
    with pytest.raises(ValueError):
        research_program(session, p, intent,
                         researcher=ScriptedResearcherClient({}),
                         llm=ScriptedLLMClient([]))


class _FailFirstCallResearcher:
    """Fails an angle's FIRST call, succeeds on the retry sweep. Thread-safe."""

    def __init__(self, flaky_angle: str):
        import threading

        self._flaky_angle = flaky_angle
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def search(self, brief):
        with self._lock:
            first_call = brief.angle not in self._seen
            self._seen.add(brief.angle)
        if first_call and brief.angle == self._flaky_angle:
            raise RuntimeError("connection reset by transient blip")
        return [RawSource(title=f"{brief.angle} source",
                          url=f"https://e.com/{brief.angle}", tier=2)]


def test_transient_angle_failure_recovers_on_second_chance_sweep(session):
    """A transient first-pass failure is retried once after the pool completes;
    the recovered angle contributes sources and emits no error event."""
    p, intent = _program(session)
    llm = ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))])
    result = research_program(
        session, p, intent,
        researcher=_FailFirstCallResearcher("phd_curricula"), llm=llm)

    kinds = [e.kind for e in result.events]
    assert "program_research:subagent_error" not in kinds
    retries = [e for e in result.events if e.kind == "program_research:subagent_retry"]
    assert len(retries) == 1
    assert retries[0].detail == "phd_curricula: recovered 1 sources"
    assert len(result.milestones) == 2  # run succeeded end-to-end


def test_subagent_error_detail_includes_exception_message(session, caplog):
    """Persistent failures must be diagnosable: the trace event carries the
    exception message (not just the class name) and the traceback is logged."""
    import logging

    p, intent = _program(session)

    class PersistentFailResearcher:
        def search(self, brief):
            if brief.angle == "phd_curricula":
                raise RuntimeError("529 overloaded upstream")
            return [RawSource(title=f"{brief.angle} source",
                              url=f"https://e.com/{brief.angle}", tier=2)]

    llm = ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))])
    with caplog.at_level(logging.ERROR):
        result = research_program(
            session, p, intent, researcher=PersistentFailResearcher(), llm=llm)

    errs = [e for e in result.events if e.kind == "program_research:subagent_error"]
    assert len(errs) == 1
    assert "RuntimeError: 529 overloaded upstream" in errs[0].detail
    assert any(r.exc_info for r in caplog.records)  # traceback logged server-side
