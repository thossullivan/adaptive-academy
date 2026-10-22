"""Defence in depth behind the schema check (llm/schema_check.py): the parsers that turn a
model's JSON into rows skip a malformed entry instead of crashing on it, and reject an answer
with nothing usable in it as StructuredOutputError (a legible 502, category invalid_output),
never AttributeError/TypeError (a bare 500). The live failure: a curriculum phase that came
back as a string."""

import json

import pytest
from sqlmodel import select

from adaptive_academy.engine.anchors import parse_anchors_json
from adaptive_academy.engine.curriculum import (
    generate_curriculum,
    parse_curriculum_json,
    parse_curriculum_obj,
)
from adaptive_academy.engine.program_research import parse_program_obj
from adaptive_academy.engine.research import _parse_foundation_json
from adaptive_academy.engine.revision import apply_change, run_revision
from adaptive_academy.llm.errors import describe_llm_error
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import StructuredOutputError
from adaptive_academy.models import (
    AgentEvent,
    MapChange,
    MapRevision,
    Milestone,
    Program,
    ProgramIntent,
    ProgramTopicLink,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
)

PHASE = {"title": "P1", "est_hours": "1w",
         "items": [{"type": "read", "text": "paper", "concept_refs": ["la"]}],
         "deliverable": {"kind": "blog", "text": "post"}}


def _invalid_output(exc: StructuredOutputError) -> None:
    failure = describe_llm_error(exc)
    assert (failure.category, failure.status_code) == ("invalid_output", 502)


# --- curriculum ---------------------------------------------------------------------------


def test_curriculum_skips_the_live_shape_and_says_where():
    dropped: list[str] = []
    tv = parse_curriculum_obj({"overview": "o", "phases": [PHASE, "Phase 2: Attention"]},
                              "T", dropped=dropped)
    assert [p.title for p in tv.phases] == ["P1"]
    assert dropped == ["$.phases[1]"]


def test_curriculum_skips_every_kind_of_malformed_entry():
    dropped: list[str] = []
    data = {
        "overview": "o",
        "phases": [{
            "title": "P1",
            "flags": ["optional", 3, None],
            "items": [{"type": "read", "text": "a", "concept_refs": ["la", 7, {"x": 1}]},
                      "read a paper", None, ["build"]],
            "deliverable": "a blog post",
        }, {"title": "P2", "items": "read everything", "deliverable": {
            "kind": "repo", "text": "code", "acceptance_criteria": ["runs", 2]}}],
        "sidebars": [{"kind": "reference", "title": "Ref", "body": "b"}, "math", 4],
    }
    tv = parse_curriculum_obj(data, "T", dropped=dropped)
    p1, p2 = tv.phases
    assert p1.flags == ["optional"]
    assert [(i.text, i.concept_refs) for i in p1.items] == [("a", ["la"])]
    assert p1.deliverable is None
    assert p2.items == []
    assert p2.deliverable.acceptance_criteria == ["runs"]
    assert [s.title for s in tv.sidebars] == ["Ref"]
    assert dropped == [
        "$.phases[0].items[1]", "$.phases[0].items[2]", "$.phases[0].items[3]",
        "$.phases[0].deliverable", "$.phases[1].items", "$.sidebars[1]", "$.sidebars[2]",
    ]


@pytest.mark.parametrize("data", [
    ["not", "an", "object"],
    "a string",
    None,
    {"overview": "o", "phases": "Phase 1, Phase 2"},
    {"overview": "o", "phases": {"title": "P1"}},
    {"overview": "o", "phases": ["Phase 1", "Phase 2"]},  # phases, none usable
])
def test_curriculum_unusable_answers_are_structured_output_errors(data):
    with pytest.raises(StructuredOutputError) as caught:
        parse_curriculum_obj(data, "T")
    _invalid_output(caught.value)


def test_curriculum_wrong_typed_sidebars_alone_are_skipped():
    dropped: list[str] = []
    tv = parse_curriculum_obj({"overview": "o", "phases": [PHASE], "sidebars": "none"}, "T",
                              dropped=dropped)
    assert [p.title for p in tv.phases] == ["P1"]
    assert tv.sidebars == [] and dropped == ["$.sidebars"]


def test_curriculum_empty_phases_is_still_an_answer():
    # The schema allows an empty list; it is the model's answer, not a malformed one.
    assert parse_curriculum_obj({"overview": "o", "phases": []}, "T").phases == []


def test_curriculum_text_path_gets_the_same_defence():
    with pytest.raises(StructuredOutputError):
        parse_curriculum_json('["Phase 1"]', "T")


# --- program research ---------------------------------------------------------------------


def test_program_skips_malformed_milestones_and_keeps_dependencies_straight():
    dropped: list[str] = []
    drafts = parse_program_obj({"milestones": [
        {"title": "A", "success_criteria": "a", "topics": [{"title": "TA"}]},
        "Milestone B",
        {"title": "C", "success_criteria": "c", "depends_on": [0, 1, True, "0"],
         "topics": ["TC", {"title": "TC2", "source_urls": ["https://e.com", 5]}, None]},
        {"title": "D", "success_criteria": "d", "depends_on": [2], "topics": "TD"},
    ]}, dropped=dropped)
    assert [d.title for d in drafts] == ["A", "C", "D"]
    # C depended on A (0) and the dropped B (1); D on C, which is now index 1.
    assert drafts[1].depends_on == [0]
    assert drafts[2].depends_on == [1]
    assert [(t.title, t.source_urls) for t in drafts[1].topics] == [("TC2", ["https://e.com"])]
    assert drafts[2].topics == []
    assert dropped == ["$.milestones[1]", "$.milestones[2].topics[0]",
                       "$.milestones[2].topics[2]", "$.milestones[3].topics"]


@pytest.mark.parametrize("data", [
    ["A", "B"], "milestones", {"milestones": "A, B"}, {"milestones": ["A", "B"]}])
def test_program_unusable_answers_are_structured_output_errors(data):
    with pytest.raises(StructuredOutputError) as caught:
        parse_program_obj(data)
    _invalid_output(caught.value)


def test_program_empty_milestones_is_still_an_answer():
    assert parse_program_obj({"milestones": []}) == []


# --- map revision -------------------------------------------------------------------------


class _Answer:
    """complete_json returning a fixed answer (the strict path: nothing re-checks it)."""

    def __init__(self, answer):
        self.answer = answer

    def complete(self, system, messages, tools):
        raise AssertionError("structured calls only")

    def complete_json(self, system, messages, *, schema, tool_name):
        return self.answer


def _program(session):
    p = Program(title="PhD prep", goal_statement="research-ready")
    session.add(p)
    session.commit()
    intent = ProgramIntent(program_id=p.id, focus_area="custom LLMs")
    session.add(intent)
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0)
    session.add(m1)
    session.commit()
    return p, m1, intent


def _researcher():
    return ScriptedResearcherClient({"whats_new": [
        RawSource(title="MoE", url="https://e.com/moe", tier=1)]})


def test_revision_skips_malformed_changes(session):
    p, m1, intent = _program(session)
    answer = {"map_health": "ok", "changes": [
        "add a topic on MoE",
        {"kind": "add_topic", "why": "gap", "source_urls": ["https://e.com", 3],
         "payload": {"milestone_id": m1.id, "title": "MoE routing"}},
        None,
    ]}
    result = run_revision(session, p, intent, researcher=_researcher(), llm=_Answer(answer))
    [change] = result.changes
    assert change.payload["title"] == "MoE routing"
    assert change.source_urls == ["https://e.com"]
    details = [e.detail for e in session.exec(select(AgentEvent)).all()
               if e.kind == "program_revision:changes_dropped"]
    assert details == ["2 invalid change(s) discarded"]


@pytest.mark.parametrize("answer", [["changes"], {"map_health": "ok", "changes": "none"}])
def test_revision_unusable_answer_is_a_structured_output_error(session, answer):
    p, _, intent = _program(session)
    with pytest.raises(StructuredOutputError) as caught:
        run_revision(session, p, intent, researcher=_researcher(), llm=_Answer(answer))
    _invalid_output(caught.value)


def test_applying_a_stored_milestone_skips_malformed_topics(session):
    p, m1, _ = _program(session)
    rev = MapRevision(program_id=p.id)
    session.add(rev)
    session.commit()
    change = MapChange(revision_id=rev.id, kind="add_milestone", payload={
        "title": "Scaling", "after_milestone_id": m1.id,
        "topics": ["Chinchilla", {"title": "Scaling laws"}, None]})
    session.add(change)
    session.commit()
    apply_change(session, p, change)
    titles = [link.proposed_title for link in session.exec(select(ProgramTopicLink)).all()]
    assert titles == ["Scaling laws"]


# --- text-parsed answers: foundation and anchors -------------------------------------------


def test_foundation_keeps_only_well_typed_parts():
    f = _parse_foundation_json(json.dumps({
        "overview": "o", "key_concepts": ["la", 3, {"x": 1}, "calc"],
        "prerequisite_map": {"calc": ["la"]}}))
    assert f.key_concepts == ["la", "calc"]
    assert f.prerequisite_map == {"calc": ["la"]}
    f = _parse_foundation_json(json.dumps({
        "overview": "o", "key_concepts": "la, calc", "prerequisite_map": ["la"]}))
    assert (f.key_concepts, f.prerequisite_map) == ([], {})


@pytest.mark.parametrize("text", ['["la", "calc"]', '"la"'])
def test_foundation_non_object_is_a_structured_output_error(text):
    with pytest.raises(StructuredOutputError) as caught:
        _parse_foundation_json(text)
    _invalid_output(caught.value)


def test_anchors_skip_malformed_entries():
    anchors = parse_anchors_json(json.dumps({"anchors": [
        "What is attention?",
        {"question": "Q", "reference_answer": "A", "key_points": ["k", 2], "concept": "c"},
        None,
    ]}))
    [a] = anchors
    assert (a.question, a.key_points, a.concept_name) == ("Q", ["k"], "c")
    assert parse_anchors_json('{"anchors": "none"}') == []


def test_anchors_non_object_is_a_structured_output_error():
    with pytest.raises(StructuredOutputError) as caught:
        parse_anchors_json('[{"question": "Q"}]')
    _invalid_output(caught.value)


# --- the curriculum run traces what it skipped ---------------------------------------------


def test_curriculum_run_skips_the_live_shape_and_traces_it(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="g")
    foundation = TopicFoundation(topic_id=topic.id, overview="o", key_concepts=["la"],
                                 prerequisite_map={})
    source = SourceDoc(topic_id=topic.id, title="S", url="u", tier=1, status="accepted")
    session.add_all([intent, foundation, source])
    session.commit()
    answer = {"overview": "o", "phases": [PHASE, "Phase 2: Attention"]}

    result = generate_curriculum(session, topic, intent, foundation, [source],
                                 llm=_Answer(answer))

    assert [p.title for p in result.track.phases] == ["P1"]
    [detail] = [e.detail for e in result.events if e.kind == "curriculum:malformed"]
    assert detail == "WARN 1 malformed entry skipped: $.phases[1]"
