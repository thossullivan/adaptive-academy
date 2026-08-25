import json
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from adaptive_academy.engine import scout
from adaptive_academy.engine.aliases import normalize_name
from adaptive_academy.engine.scout import Candidate, ScoutResult, maybe_scout, rank
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    Milestone,
    Program,
    ProgramTopicLink,
    Topic,
    TopicSuggestion,
    Track,
)


def _program(session):
    program = Program(title="Research path", goal_statement="Find new retrieval methods")
    session.add(program)
    session.flush()
    milestone = Milestone(program_id=program.id, title="Retrieval foundations")
    session.add(milestone)
    session.flush()
    return program, milestone


def _candidates() -> list[Candidate]:
    return [
        Candidate(
            kind="orphan_term",
            label=f"Candidate {index}",
            evidence=[{"kind": "chunk", "ref": f"message:{index}"}],
            weight=float(10 - index),
        )
        for index in range(6)
    ]


def _rank_payload(*, title_prefix="Topic", invalid_title="Ungrounded") -> str:
    items = [
        {
            "title": f"{title_prefix} {index}",
            "rationale": f"Reason {index}",
            "candidate_kind": "orphan_term",
            "evidence_indexes": [index],
            "score": 0.9 - index / 10,
        }
        for index in range(2)
    ]
    items.append(
        {
            "title": invalid_title,
            "rationale": "No evidence",
            "candidate_kind": "orphan_term",
            "evidence_indexes": [],
            "score": 1.0,
        }
    )
    items.extend(
        {
            "title": f"{title_prefix} {index}",
            "rationale": f"Reason {index}",
            "candidate_kind": "orphan_term",
            "evidence_indexes": [index],
            "score": 0.9 - index / 10,
        }
        for index in range(2, 5)
    )
    return json.dumps({"items": items})


def test_rank_stores_five_grounded_items_and_resolves_evidence(session):
    program, _milestone = _program(session)
    llm = ScriptedLLMClient([LLMResponse(text=_rank_payload())])

    suggestions = rank(session, program, _candidates(), llm=llm)

    assert len(suggestions) == 5
    assert len(session.exec(select(TopicSuggestion)).all()) == 5
    assert suggestions[0].evidence == [{"kind": "chunk", "ref": "message:0"}]
    assert all(suggestion.program_id == program.id for suggestion in suggestions)
    assert len(llm.calls) == 1
    assert "<<<CANDIDATES>>>" in llm.calls[0]["messages"][0]["content"]
    assert "<<<END_CANDIDATES>>>" in llm.calls[0]["messages"][0]["content"]
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "scout:ranked")
    ).one()
    assert event.program_id == program.id


def test_rank_upserts_normalized_titles_without_duplicates(session):
    program, _milestone = _program(session)
    first_llm = ScriptedLLMClient([LLMResponse(text=_rank_payload())])
    first = rank(session, program, _candidates(), llm=first_llm)
    first_ids = {normalize_name(item.title): item.id for item in first}

    payload = json.loads(_rank_payload(title_prefix="Topic"))
    for item in payload["items"]:
        if not item["title"].startswith("Topic "):
            continue
        index = int(item["title"].rsplit(maxsplit=1)[1])
        item["title"] = f"  TOPIC {index}  "
        item["rationale"] = f"Updated {index}"
    second = rank(
        session,
        program,
        _candidates(),
        llm=ScriptedLLMClient([LLMResponse(text=json.dumps(payload))]),
    )

    stored = session.exec(select(TopicSuggestion)).all()
    assert len(stored) == 5
    assert {normalize_name(item.title): item.id for item in second} == first_ids
    assert {item.rationale for item in stored} == {
        f"Updated {index}" for index in range(5)
    }


def test_rank_does_not_repropose_recently_dismissed_title(session):
    program, _milestone = _program(session)
    dismissed = TopicSuggestion(
        program_id=program.id,
        title="Topic 0",
        rationale="Dismissed",
        candidate_kind="orphan_term",
        status="dismissed",
        decided_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    session.add(dismissed)
    session.commit()

    suggestions = rank(
        session,
        program,
        _candidates(),
        llm=ScriptedLLMClient([LLMResponse(text=_rank_payload())]),
    )

    session.refresh(dismissed)
    assert dismissed.status == "dismissed"
    assert all(normalize_name(item.title) != "topic 0" for item in suggestions)
    assert len(session.exec(select(TopicSuggestion)).all()) == 5


def test_maybe_scout_fires_at_25_assessments_but_not_24(session, monkeypatch):
    program, milestone = _program(session)
    topic = Topic(title="Retrieval")
    session.add(topic)
    session.flush()
    track = Track(topic_id=topic.id, title="Retrieval")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="Ranking")
    session.add(concept)
    session.flush()
    session.add(
        ProgramTopicLink(
            milestone_id=milestone.id,
            topic_id=topic.id,
            status="started",
            proposed_title=topic.title,
        )
    )
    for index in range(24):
        session.add(
            Assessment(
                concept_id=concept.id,
                kind="self_explanation",
                prompt=f"Probe {index}",
            )
        )
    session.commit()

    calls = []

    def fake_run_scout(session_arg, program_arg, *, llm):
        calls.append((session_arg, program_arg, llm))
        return ScoutResult(suggestions=[], counts={}, truncated=False)

    monkeypatch.setattr(scout, "run_scout", fake_run_scout)
    llm = ScriptedLLMClient([])

    assert maybe_scout(session, program.id, llm=llm) is None
    assert calls == []

    session.add(
        Assessment(
            concept_id=concept.id,
            kind="self_explanation",
            prompt="Probe 25",
        )
    )
    session.commit()

    result = maybe_scout(session, program.id, llm=llm)

    assert result == ScoutResult(suggestions=[], counts={}, truncated=False)
    assert len(calls) == 1
