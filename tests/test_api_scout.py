import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Chunk,
    Milestone,
    Program,
    ProgramTopicLink,
    TopicSuggestion,
)


def _seed_program(session: Session) -> tuple[Program, Milestone]:
    program = Program(title="Research path", goal_statement="Find retrieval methods")
    session.add(program)
    session.flush()
    milestone = Milestone(program_id=program.id, title="Retrieval foundations")
    session.add(milestone)
    session.commit()
    return program, milestone


def _client(session: Session, payload: dict | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    rank_payload = payload or {
        "items": [
            {
                "title": "Sparse retrieval",
                "rationale": "The note identifies an uncovered research direction.",
                "candidate_kind": "orphan_note",
                "evidence_indexes": [0],
                "score": 0.91,
            }
        ]
    }
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps(rank_payload))]
    )
    return TestClient(app)


def _suggestion(session: Session, program: Program, *, title: str) -> TopicSuggestion:
    suggestion = TopicSuggestion(
        program_id=program.id,
        title=title,
        rationale="Grounded rationale",
        candidate_kind="frontier",
        evidence=[{"kind": "concept", "id": 42}],
        score=0.8,
    )
    session.add(suggestion)
    session.commit()
    session.refresh(suggestion)
    return suggestion


def test_run_scout_returns_suggestions_and_candidate_counts(session):
    program, _milestone = _seed_program(session)
    session.add(
        Chunk(
            kind="vault_note",
            source_ref="file:///vault/sparse-retrieval.md",
            text="Sparse retrieval ideas",
            context="Sparse retrieval",
            content_hash="scout-note",
        )
    )
    session.commit()
    client = _client(session)

    response = client.post(f"/api/programs/{program.id}/scout")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidates"] == {
        "frontier": 0,
        "orphan_term": 0,
        "orphan_note": 1,
        "extension": 0,
    }
    assert body["suggestions"][0]["title"] == "Sparse retrieval"
    assert body["suggestions"][0]["evidence"] == [
        {"kind": "chunk", "ref": "file:///vault/sparse-retrieval.md"}
    ]


def test_list_suggestions_filters_by_status(session):
    program, _milestone = _seed_program(session)
    proposed = _suggestion(session, program, title="Proposed topic")
    dismissed = _suggestion(session, program, title="Dismissed topic")
    dismissed.status = "dismissed"
    session.add(dismissed)
    session.commit()
    client = _client(session)

    response = client.get(
        f"/api/programs/{program.id}/suggestions?status=proposed"
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [proposed.id]


def test_accept_suggestion_creates_stub_and_marks_decision(session):
    program, milestone = _seed_program(session)
    suggestion = _suggestion(session, program, title="Sparse retrieval")
    client = _client(session)

    response = client.post(
        f"/api/suggestions/{suggestion.id}/accept",
        json={"milestone_id": milestone.id},
    )

    assert response.status_code == 200, response.text
    session.refresh(suggestion)
    assert suggestion.status == "accepted"
    assert suggestion.decided_at is not None
    link = session.exec(select(ProgramTopicLink)).one()
    assert link.milestone_id == milestone.id
    assert link.topic_id is None
    assert link.status == "stub"
    assert link.proposed_title == suggestion.title
    assert link.why == suggestion.rationale
    assert link.added_by == "scout"
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "scout:accepted")
    ).one()
    assert event.program_id == program.id


def test_accept_requires_a_current_program_milestone(session):
    program, _milestone = _seed_program(session)
    suggestion = _suggestion(session, program, title="Sparse retrieval")
    other = Program(title="Other")
    session.add(other)
    session.flush()
    wrong_milestone = Milestone(program_id=other.id, title="Other milestone")
    archived = Milestone(program_id=program.id, title="Archived", archived=True)
    session.add(wrong_milestone)
    session.add(archived)
    session.commit()
    client = _client(session)

    missing = client.post(
        f"/api/suggestions/{suggestion.id}/accept",
    )
    wrong = client.post(
        f"/api/suggestions/{suggestion.id}/accept",
        json={"milestone_id": wrong_milestone.id},
    )

    archived_resp = client.post(
        f"/api/suggestions/{suggestion.id}/accept",
        json={"milestone_id": archived.id},
    )

    assert missing.status_code == 400
    assert wrong.status_code == 400
    assert archived_resp.status_code == 400
    assert session.exec(select(ProgramTopicLink)).all() == []


def test_dismiss_suggestion_marks_decision_and_emits_event(session):
    program, _milestone = _seed_program(session)
    suggestion = _suggestion(session, program, title="Sparse retrieval")
    client = _client(session)

    response = client.post(f"/api/suggestions/{suggestion.id}/dismiss")

    assert response.status_code == 200, response.text
    session.refresh(suggestion)
    assert suggestion.status == "dismissed"
    assert suggestion.decided_at is not None
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "scout:dismissed")
    ).one()
    assert event.program_id == program.id


def test_accepting_suggestion_twice_returns_conflict(session):
    program, milestone = _seed_program(session)
    suggestion = _suggestion(session, program, title="Sparse retrieval")
    client = _client(session)

    first = client.post(
        f"/api/suggestions/{suggestion.id}/accept",
        json={"milestone_id": milestone.id},
    )
    second = client.post(
        f"/api/suggestions/{suggestion.id}/accept",
        json={"milestone_id": milestone.id},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert len(session.exec(select(ProgramTopicLink)).all()) == 1
