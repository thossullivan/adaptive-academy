"""The Attempt button (docs/superpowers/specs/2026-10-23-attempt-button-design.md).

The learner, not the tutor, says "this is my attempt": POST .../messages takes `attempt: true`,
and before the tutor runs the code checks the message (the solution guard's learner_attempted
judgement), writes an Attempt row, sets Conversation.attempt_logged on a real attempt, traces
fixed-label attempt:* events, and tells the tutor what happened in a fixed system note. The
tutor no longer has a log_attempt tool on either path. All model calls are scripted.
"""

import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import adaptive_academy.engine.solution_guard as solution_guard
import adaptive_academy.engine.tutor_sdk as tutor_sdk
from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_guard_llm, get_llm, get_retriever, get_session
from adaptive_academy.db import ensure_fts
from adaptive_academy.engine.attempt import ACCEPTED, ALREADY_LOGGED, REJECTED, UNVERIFIED
from adaptive_academy.engine.tools import TOOLS
from adaptive_academy.engine.tutor import run_tutor_turn
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
from adaptive_academy.llm.types import LLMResponse, ToolCall
from adaptive_academy.models import (
    AgentEvent,
    Attempt,
    Concept,
    Conversation,
    KnowledgeEstimate,
    Message,
    Topic,
    Track,
)
from adaptive_academy.prompts import (
    TUTOR_ATTEMPT_ACCEPTED,
    TUTOR_ATTEMPT_ALREADY_LOGGED,
    TUTOR_ATTEMPT_REJECTED,
    TUTOR_ATTEMPT_UNVERIFIED,
    TUTOR_BASE,
    TUTOR_SOLUTION_GUARD,
    TUTOR_STATE_LOCKED,
    TUTOR_STATE_UNLOCKED,
)

GUESS = "I think it's 42"
REAL = "I'd divide by sqrt(d_k) because the variance grows with dimension"
HINT = "What does each row of QK^T measure, before any normalisation?"
SECRET = "THE SECRET: softmax(QK^T / sqrt(d_k)) V"
ALL_NOTES = (TUTOR_ATTEMPT_ACCEPTED, TUTOR_ATTEMPT_REJECTED, TUTOR_ATTEMPT_UNVERIFIED,
             TUTOR_ATTEMPT_ALREADY_LOGGED)


def _seed(session, *, attempt_logged=False) -> Conversation:
    topic = Topic(title="LLMs")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="self-attention")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
    convo = Conversation(topic_id=topic.id, concept_id=concept.id,
                         attempt_logged=attempt_logged)
    session.add(convo)
    session.commit()
    return convo


def _verdict(*, attempted: bool, gives_away: bool = False) -> LLMResponse:
    return LLMResponse(text=json.dumps({"gives_away_solution": gives_away,
                                        "learner_attempted": attempted, "reason": "r"}))


class _BrokenGuard:
    def __init__(self):
        self.calls = 0

    def complete(self, system, messages, tools):
        self.calls += 1
        raise RuntimeError("guard model unavailable")


def _reveal_then_hint() -> list[LLMResponse]:
    """The tutor tries to reveal; if the gate blocks it, it hints instead."""
    return [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="reveal_solution",
                                         input={"text": SECRET})]),
        LLMResponse(text=HINT),
    ]


def _kinds(result) -> list[str]:
    return [e.kind for e in result.events]


def _attempt_rows(session) -> list[Attempt]:
    session.expire_all()
    return list(session.exec(select(Attempt).order_by(Attempt.id)).all())


def _user_message(session, convo) -> Message:
    session.expire_all()
    return session.exec(select(Message).where(Message.conversation_id == convo.id,
                                              Message.role == "user")
                        .order_by(Message.id.desc())).first()


# --- the tutor has no log_attempt tool ------------------------------------------------------


def test_the_tutor_has_only_the_gated_reveal_tool():
    assert [t["name"] for t in TOOLS] == ["reveal_solution"]


def test_the_tutor_prompt_points_at_the_button_and_not_a_tool():
    text = " ".join(str(TUTOR_BASE).split())
    assert TUTOR_BASE.tag == "tutor.base@v5"
    assert "log_attempt" not in text
    assert "Submit attempt" in text
    assert "If that's your attempt, submit it with Submit attempt" in text


def test_the_guard_prompt_check_line_is_about_a_submitted_attempt():
    text = " ".join(str(TUTOR_SOLUTION_GUARD).split())
    assert TUTOR_SOLUTION_GUARD.tag == "tutor.solution_guard@v5"
    assert "the tutor wants to record" not in text
    assert "submitted" in text and "CHECK:" in text


def test_attempt_notes_are_versioned_and_never_invite_a_later_reveal():
    for note in ALL_NOTES:
        assert note.tag.startswith("tutor.attempt_")
        assert "—" not in note
    for note in (TUTOR_ATTEMPT_REJECTED, TUTOR_ATTEMPT_UNVERIFIED):
        text = note.lower()
        assert "do not state, promise, or schedule the solution" in text
        assert "submit attempt" in text


def test_a_hallucinated_log_attempt_call_unlocks_nothing(session):
    convo = _seed(session)
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="log_attempt",
                                         input={"summary": "tried"})]),
        *_reveal_then_hint(),
    ])
    guard = ScriptedLLMClient([_verdict(attempted=True)])  # the review of the hint only

    result = run_tutor_turn(session, convo, REAL, llm, guard_llm=guard)

    session.refresh(convo)
    assert convo.attempt_logged is False and result.reply == HINT
    assert "tool:log_attempt:unknown" in _kinds(result)
    assert "tool:reveal_solution:blocked" in _kinds(result)
    assert _attempt_rows(session) == []


# --- API-key tutor path ---------------------------------------------------------------------


def test_an_ordinary_message_runs_no_attempt_check(session):
    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text=HINT)])
    guard = ScriptedLLMClient([_verdict(attempted=True)])  # the reply review only

    result = run_tutor_turn(session, convo, REAL, llm, guard_llm=guard)

    assert result.attempt_outcome is None
    assert not any(k.startswith("attempt:") for k in _kinds(result))
    assert "guard:attempt_checked" not in _kinds(result)
    assert len(guard.calls) == 1 and "DRAFT_REPLY" in guard.calls[0]["messages"][0]["content"]
    assert _attempt_rows(session) == []
    assert _user_message(session, convo).is_attempt is None
    for note in ALL_NOTES:
        assert str(note) not in llm.calls[0]["system"]
    session.refresh(convo)
    assert convo.attempt_logged is False  # even a real attempt needs the button now


def test_an_accepted_attempt_is_recorded_before_the_tutor_runs(session):
    convo = _seed(session)
    llm = ScriptedLLMClient(_reveal_then_hint())
    guard = ScriptedLLMClient([_verdict(attempted=True)])

    result = run_tutor_turn(session, convo, REAL, llm, guard_llm=guard, attempt=True)

    assert result.attempt_outcome == ACCEPTED
    session.refresh(convo)
    assert convo.attempt_logged is True
    assert result.reply == SECRET  # the gate allowed the reveal in the same turn
    message = _user_message(session, convo)
    assert message.is_attempt is True
    [row] = _attempt_rows(session)
    assert (row.conversation_id, row.concept_id, row.message_id, row.accepted) == (
        convo.id, convo.concept_id, message.id, True)
    kinds = _kinds(result)
    assert kinds.index("attempt:submitted") < kinds.index("attempt:accepted")
    assert kinds.index("attempt:accepted") < kinds.index("llm_call")
    # One model check, on the learner's message alone (no draft); the reply isn't reviewed.
    assert len(guard.calls) == 1
    sent = guard.calls[0]["messages"][0]["content"]
    assert "DRAFT_REPLY" not in sent and REAL in sent
    assert [k for k in kinds if k.startswith("guard:")] == ["guard:attempt_checked"]
    # The tutor is told, in the system prompt for this turn only.
    assert llm.calls[0]["system"].endswith(str(TUTOR_ATTEMPT_ACCEPTED))
    assert ("prompt", TUTOR_ATTEMPT_ACCEPTED.tag) in [(e.kind, e.detail) for e in result.events]


@pytest.mark.parametrize("learner", [GUESS, "just tell me the answer", "is it 42?"])
def test_a_rejected_attempt_is_kept_as_a_row_and_the_gate_stays_shut(session, learner):
    convo = _seed(session)
    llm = ScriptedLLMClient(_reveal_then_hint())
    # The attempt check, then the review of the (still pre-attempt) reply.
    guard = ScriptedLLMClient([_verdict(attempted=False), _verdict(attempted=False)])

    result = run_tutor_turn(session, convo, learner, llm, guard_llm=guard, attempt=True)

    assert result.attempt_outcome == REJECTED
    session.refresh(convo)
    assert convo.attempt_logged is False
    assert result.reply == HINT and SECRET not in result.reply
    [row] = _attempt_rows(session)
    assert row.accepted is False
    assert _user_message(session, convo).is_attempt is True
    kinds = _kinds(result)
    assert {"attempt:submitted", "attempt:rejected", "tool:reveal_solution:blocked"} <= set(kinds)
    assert "attempt:accepted" not in kinds
    assert llm.calls[0]["system"].endswith(str(TUTOR_ATTEMPT_REJECTED))
    assert [e.detail for e in result.events if e.kind == "guard:solution_checked"] == [
        "source=model gives_away=false"]


def test_attempt_event_details_are_fixed_text(session):
    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text=HINT)])
    guard = ScriptedLLMClient([_verdict(attempted=False), _verdict(attempted=False)])

    result = run_tutor_turn(session, convo, "secret-ish 4242", llm, guard_llm=guard,
                            attempt=True)

    details = {e.kind: e.detail for e in result.events if e.kind.startswith("attempt:")}
    assert details == {
        "attempt:submitted": "the learner submitted this message as an attempt",
        "attempt:rejected": "not recorded: no reasoning, step, or working in the message",
    }


@pytest.mark.parametrize("guard_llm", [_BrokenGuard, None])
def test_an_unverified_attempt_is_not_recorded_and_the_turn_completes(
        session, monkeypatch, guard_llm):
    monkeypatch.setattr(solution_guard, "_warned_attempt_unchecked", True)
    monkeypatch.setattr(solution_guard, "_warned_degraded", True)
    convo = _seed(session)
    llm = ScriptedLLMClient(_reveal_then_hint())

    result = run_tutor_turn(session, convo, REAL, llm,
                            guard_llm=guard_llm() if guard_llm else None, attempt=True)

    assert result.attempt_outcome == UNVERIFIED
    session.refresh(convo)
    assert convo.attempt_logged is False and result.reply == HINT
    assert _attempt_rows(session) == []  # not recorded either way
    assert _user_message(session, convo).is_attempt is True
    kinds = _kinds(result)
    assert "attempt:unverified" in kinds and "attempt:rejected" not in kinds
    assert kinds.count("guard:attempt_unavailable") == 1
    assert ("attempt:unverified", "not recorded: the attempt check was unavailable") in [
        (e.kind, e.detail) for e in result.events]
    assert llm.calls[0]["system"].endswith(str(TUTOR_ATTEMPT_UNVERIFIED))


def test_an_attempt_in_an_unlocked_conversation_needs_no_check(session):
    convo = _seed(session, attempt_logged=True)
    llm = ScriptedLLMClient([LLMResponse(text="Good. Why sqrt and not d_k?")])
    guard = ScriptedLLMClient([])  # any call would raise "ran out of responses"

    result = run_tutor_turn(session, convo, "is it 42?", llm, guard_llm=guard, attempt=True)

    assert result.attempt_outcome == ALREADY_LOGGED
    assert guard.calls == []
    assert _attempt_rows(session) == []
    assert _user_message(session, convo).is_attempt is True
    kinds = _kinds(result)
    assert [k for k in kinds if k.startswith("attempt:")] == ["attempt:submitted"]
    assert not any(k.startswith("guard:") for k in kinds)
    assert llm.calls[0]["system"].endswith(str(TUTOR_ATTEMPT_ALREADY_LOGGED))


def test_a_second_attempt_after_a_rejection_can_open_the_gate(session):
    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text=HINT), *_reveal_then_hint()])
    first_guard = ScriptedLLMClient([_verdict(attempted=False), _verdict(attempted=False)])
    run_tutor_turn(session, convo, GUESS, llm, guard_llm=first_guard, attempt=True)

    result = run_tutor_turn(session, convo, REAL, llm,
                            guard_llm=ScriptedLLMClient([_verdict(attempted=True)]),
                            attempt=True)

    assert result.attempt_outcome == ACCEPTED and result.reply == SECRET
    assert [r.accepted for r in _attempt_rows(session)] == [False, True]


def test_no_write_lock_is_held_during_the_attempt_check(tmp_path):
    path = tmp_path / "attempt.db"
    engine = create_engine(f"sqlite:///{path}",
                           connect_args={"check_same_thread": False, "timeout": 1})
    SQLModel.metadata.create_all(engine)
    ensure_fts(engine)

    def lock_free() -> bool:
        conn = sqlite3.connect(path, timeout=0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
            return True
        except sqlite3.OperationalError:
            return False
        finally:
            conn.close()

    class _ProbingGuard:
        def __init__(self):
            self.lock_free: list[bool] = []

        def complete(self, system, messages, tools):
            self.lock_free.append(lock_free())
            return _verdict(attempted=True)

    with Session(engine) as session:
        convo = _seed(session)
        guard = _ProbingGuard()
        result = run_tutor_turn(session, convo, REAL, ScriptedLLMClient(_reveal_then_hint()),
                                guard_llm=guard, attempt=True)
    engine.dispose()

    assert result.reply == SECRET
    assert guard.lock_free == [True]


# --- Agent SDK (subscription) tutor path ----------------------------------------------------


class _FakeResult:
    def __init__(self, result, is_error=False):
        self.result = result
        self.is_error = is_error


def _sdk_turn(session, monkeypatch, *, learner, guard_llm, attempt, attempt_logged=False):
    """An SDK turn whose run calls the REAL reveal_solution handler with SECRET; its reply
    is SECRET if the reveal was allowed, else HINT."""
    convo = _seed(session, attempt_logged=attempt_logged)
    captured: dict = {}
    seen: dict = {}
    real_server = tutor_sdk.create_sdk_mcp_server

    def capture_server(name, tools):
        captured.update({t.name: t for t in tools})
        return real_server(name, tools=tools)

    async def fake_query(prompt, options):
        seen["allowed_tools"] = options.allowed_tools
        seen["tools"] = options.tools
        seen["permission_mode"] = options.permission_mode
        seen["system"] = options.system_prompt
        revealed = await captured["reveal_solution"].handler({"text": SECRET})
        yield _FakeResult(SECRET if not revealed.get("is_error") else HINT)

    monkeypatch.setattr(tutor_sdk, "create_sdk_mcp_server", capture_server)
    monkeypatch.setattr(tutor_sdk, "ResultMessage", _FakeResult)
    monkeypatch.setattr(tutor_sdk, "query", fake_query)
    monkeypatch.setattr(tutor_sdk, "record_sdk_result", lambda *a, **kw: None)
    result = tutor_sdk.run_tutor_turn_sdk(session, convo, learner, guard_llm=guard_llm,
                                          attempt=attempt)
    session.refresh(convo)
    return convo, result, captured, seen


def test_sdk_the_tutor_has_only_the_reveal_tool(session, monkeypatch):
    _, _, captured, seen = _sdk_turn(session, monkeypatch, learner="hi", attempt=False,
                                     guard_llm=ScriptedLLMClient([_verdict(attempted=False)]))
    assert set(captured) == {"reveal_solution"}
    assert seen["allowed_tools"] == ["mcp__tutor__reveal_solution"]
    # Security: with bypassPermissions, `tools` must turn off every built-in Claude Code tool
    # (Bash, Read, Write, ...). allowed_tools alone only auto-approves; it doesn't restrict.
    assert seen["permission_mode"] == "bypassPermissions" and seen["tools"] == []


def test_sdk_an_accepted_attempt_opens_the_gate(session, monkeypatch):
    guard = ScriptedLLMClient([_verdict(attempted=True)])
    convo, result, _, seen = _sdk_turn(session, monkeypatch, learner=REAL, guard_llm=guard,
                                       attempt=True)

    assert result.attempt_outcome == ACCEPTED
    assert convo.attempt_logged is True and result.reply == SECRET
    assert [r.accepted for r in _attempt_rows(session)] == [True]
    assert str(TUTOR_ATTEMPT_ACCEPTED) in seen["system"]
    assert len(guard.calls) == 1


def test_sdk_a_rejected_attempt_keeps_the_gate_shut(session, monkeypatch):
    guard = ScriptedLLMClient([_verdict(attempted=False), _verdict(attempted=False)])
    convo, result, _, seen = _sdk_turn(session, monkeypatch, learner=GUESS, guard_llm=guard,
                                       attempt=True)

    assert result.attempt_outcome == REJECTED
    assert convo.attempt_logged is False and result.reply == HINT
    assert [r.accepted for r in _attempt_rows(session)] == [False]
    assert "tool:reveal_solution:blocked" in _kinds(result)
    assert str(TUTOR_ATTEMPT_REJECTED) in seen["system"]
    assert len(guard.calls) == 2  # the attempt check, then the review of the reply


def test_sdk_an_unverified_attempt_is_not_recorded(session, monkeypatch):
    monkeypatch.setattr(solution_guard, "_warned_attempt_unchecked", True)
    monkeypatch.setattr(solution_guard, "_warned_degraded", True)
    convo, result, _, seen = _sdk_turn(session, monkeypatch, learner=REAL,
                                       guard_llm=_BrokenGuard(), attempt=True)

    assert result.attempt_outcome == UNVERIFIED
    assert convo.attempt_logged is False and result.reply == HINT
    assert _attempt_rows(session) == []
    assert "attempt:unverified" in _kinds(result)
    assert str(TUTOR_ATTEMPT_UNVERIFIED) in seen["system"]


def test_sdk_an_attempt_in_an_unlocked_conversation_needs_no_check(session, monkeypatch):
    guard = ScriptedLLMClient([])
    convo, result, _, _ = _sdk_turn(session, monkeypatch, learner="is it 42?",
                                    guard_llm=guard, attempt=True, attempt_logged=True)

    assert result.attempt_outcome == ALREADY_LOGGED and guard.calls == []
    assert _attempt_rows(session) == [] and result.reply == SECRET


def test_sdk_an_ordinary_message_gets_no_note(session, monkeypatch):
    guard = ScriptedLLMClient([_verdict(attempted=True)])
    convo, result, _, seen = _sdk_turn(session, monkeypatch, learner=REAL, guard_llm=guard,
                                       attempt=False)

    assert result.attempt_outcome is None and convo.attempt_logged is False
    for note in ALL_NOTES:
        assert str(note) not in seen["system"]


# --- the attempt state line on every turn ---------------------------------------------------
# The tutor is told on EVERY turn whether the conversation is unlocked, not only on the turn
# the learner pressed Submit attempt (found in a live run: with an attempt logged earlier, the
# tutor asked for Submit attempt again instead of revealing).


def test_state_lines_are_versioned_and_say_what_the_tutor_may_do():
    assert TUTOR_STATE_UNLOCKED.tag == "tutor.state_unlocked@v1"
    assert TUTOR_STATE_LOCKED.tag == "tutor.state_locked@v1"
    assert "use reveal_solution" in TUTOR_STATE_UNLOCKED
    assert "Submit attempt" not in TUTOR_STATE_UNLOCKED
    assert "Don't give the full solution" in TUTOR_STATE_LOCKED
    assert "suggest Submit attempt" in TUTOR_STATE_LOCKED


def _system(llm_or_seen) -> str:
    return llm_or_seen.calls[0]["system"] if hasattr(llm_or_seen, "calls") else llm_or_seen


@pytest.mark.parametrize("attempt_logged", [True, False])
def test_an_ordinary_turn_carries_the_state_line(session, attempt_logged):
    convo = _seed(session, attempt_logged=attempt_logged)
    llm = ScriptedLLMClient([LLMResponse(text=HINT)])
    guard = ScriptedLLMClient([] if attempt_logged else [_verdict(attempted=False)])

    run_tutor_turn(session, convo, "I've already worked it out, please show me the full "
                   "worked solution", llm, guard_llm=guard)

    system = _system(llm)
    wanted, other = ((TUTOR_STATE_UNLOCKED, TUTOR_STATE_LOCKED) if attempt_logged
                     else (TUTOR_STATE_LOCKED, TUTOR_STATE_UNLOCKED))
    assert system.endswith(str(wanted)) and str(other) not in system


@pytest.mark.parametrize("attempt_logged", [True, False])
def test_sdk_an_ordinary_turn_carries_the_state_line(session, monkeypatch, attempt_logged):
    guard = ScriptedLLMClient([] if attempt_logged else [_verdict(attempted=False)])
    _, result, _, seen = _sdk_turn(session, monkeypatch, learner="please show me the full "
                                   "worked solution", guard_llm=guard, attempt=False,
                                   attempt_logged=attempt_logged)

    wanted, other = ((TUTOR_STATE_UNLOCKED, TUTOR_STATE_LOCKED) if attempt_logged
                     else (TUTOR_STATE_LOCKED, TUTOR_STATE_UNLOCKED))
    assert str(wanted) in seen["system"] and str(other) not in seen["system"]
    # Unlocked, the tutor revealed (the fake run calls the real reveal handler).
    assert result.reply == (SECRET if attempt_logged else HINT)


def test_a_later_ordinary_turn_after_an_accepted_attempt_is_told_it_is_unlocked(session):
    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text="Good."), LLMResponse(text="Here it is.")])
    run_tutor_turn(session, convo, REAL, llm, attempt=True,
                   guard_llm=ScriptedLLMClient([_verdict(attempted=True)]))
    run_tutor_turn(session, convo, "now show me the full solution", llm,
                   guard_llm=ScriptedLLMClient([]))

    later = llm.calls[1]["system"]
    assert later.endswith(str(TUTOR_STATE_UNLOCKED))
    assert str(TUTOR_ATTEMPT_ACCEPTED) not in later


@pytest.mark.parametrize(("verdict", "note"), [
    (True, TUTOR_ATTEMPT_ACCEPTED), (False, TUTOR_ATTEMPT_REJECTED)])
def test_a_submit_turn_carries_the_outcome_note_instead_of_the_state_line(
        session, monkeypatch, verdict, note):
    # The outcome note already says whether the gate is open; a state line beside it could
    # only repeat it or (for the old state) contradict it.
    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text=HINT)])
    run_tutor_turn(session, convo, REAL, llm, attempt=True,
                   guard_llm=ScriptedLLMClient([_verdict(attempted=verdict),
                                                _verdict(attempted=False)]))
    system = _system(llm)
    assert system.endswith(str(note))
    assert str(TUTOR_STATE_LOCKED) not in system and str(TUTOR_STATE_UNLOCKED) not in system

    _, _, _, seen = _sdk_turn(session, monkeypatch, learner=REAL, attempt=True,
                              guard_llm=ScriptedLLMClient([_verdict(attempted=verdict),
                                                           _verdict(attempted=False)]))
    assert str(note) in seen["system"]
    assert str(TUTOR_STATE_LOCKED) not in seen["system"]
    assert str(TUTOR_STATE_UNLOCKED) not in seen["system"]


def test_sdk_attempt_check_works_with_a_client_that_runs_its_own_event_loop(
        session, monkeypatch):
    # The subscription guard client (AgentSDKLLMClient) calls asyncio.run per check, which
    # raises inside a running loop. The check runs before the SDK query, outside any loop.
    class _LoopingGuard(ScriptedLLMClient):
        def complete(self, system, messages, tools):
            async def _call():
                return ScriptedLLMClient.complete(self, system, messages, tools)
            return asyncio.run(_call())

    convo, result, _, _ = _sdk_turn(session, monkeypatch, learner=REAL, attempt=True,
                                    guard_llm=_LoopingGuard([_verdict(attempted=True)]))

    assert "guard:attempt_unavailable" not in _kinds(result)
    assert convo.attempt_logged is True and result.reply == SECRET


# --- the route ------------------------------------------------------------------------------


def _client(session, *, llm, guard):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_guard_llm] = lambda: guard
    app.dependency_overrides[get_retriever] = lambda: ScriptedRetriever()
    return TestClient(app)


def test_route_attempt_defaults_to_false(session):
    convo = _seed(session)
    client = _client(session, llm=ScriptedLLMClient([LLMResponse(text=HINT)]),
                     guard=ScriptedLLMClient([_verdict(attempted=True)]))

    body = client.post(f"/api/conversations/{convo.id}/messages",
                       json={"content": REAL}).json()

    assert body["attempt_outcome"] is None and body["attempt_logged"] is False
    messages = client.get(f"/api/conversations/{convo.id}").json()["messages"]
    assert [m["is_attempt"] for m in messages] == [False, False]


def test_route_accepted_attempt(session):
    convo = _seed(session)
    client = _client(session, llm=ScriptedLLMClient(_reveal_then_hint()),
                     guard=ScriptedLLMClient([_verdict(attempted=True)]))

    r = client.post(f"/api/conversations/{convo.id}/messages",
                    json={"content": REAL, "attempt": True})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["attempt_outcome"] == "accepted" and body["attempt_logged"] is True
    assert body["reply"] == SECRET
    assert {"attempt:submitted", "attempt:accepted"} <= {e["kind"] for e in body["events"]}
    messages = client.get(f"/api/conversations/{convo.id}").json()["messages"]
    assert [(m["role"], m["is_attempt"]) for m in messages] == [("user", True),
                                                                 ("tutor", False)]


def test_route_rejected_attempt(session):
    convo = _seed(session)
    client = _client(session, llm=ScriptedLLMClient(_reveal_then_hint()),
                     guard=ScriptedLLMClient([_verdict(attempted=False),
                                              _verdict(attempted=False)]))

    body = client.post(f"/api/conversations/{convo.id}/messages",
                       json={"content": GUESS, "attempt": True}).json()

    assert body["attempt_outcome"] == "rejected" and body["attempt_logged"] is False
    assert SECRET not in body["reply"]
    session.expire_all()
    kinds = {e.kind for e in session.exec(select(AgentEvent)).all()}
    assert "attempt:rejected" in kinds


def test_route_rejects_a_non_boolean_attempt(session):
    convo = _seed(session)
    client = _client(session, llm=ScriptedLLMClient([]), guard=ScriptedLLMClient([]))
    r = client.post(f"/api/conversations/{convo.id}/messages",
                    json={"content": REAL, "attempt": "maybe"})
    assert r.status_code == 422


@pytest.mark.parametrize("content", ["", "   ", "\n\t "])
@pytest.mark.parametrize("attempt", [True, False])
def test_route_rejects_blank_content_before_any_model_call(session, content, attempt):
    # A blank attempt must not run the paid check or write a rejected row; a blank message
    # must not reach the tutor either.
    convo = _seed(session)
    llm, guard = ScriptedLLMClient([]), ScriptedLLMClient([])
    client = _client(session, llm=llm, guard=guard)

    r = client.post(f"/api/conversations/{convo.id}/messages",
                    json={"content": content, "attempt": attempt})

    assert r.status_code == 422
    assert llm.calls == [] and guard.calls == []
    session.expire_all()
    assert session.exec(select(Message)).all() == []
    assert _attempt_rows(session) == []


def test_get_conversation_reports_each_attempts_outcome(session, monkeypatch):
    # After a reload the transcript must still tell a rejected attempt from an accepted one.
    monkeypatch.setattr(solution_guard, "_warned_attempt_unchecked", True)
    monkeypatch.setattr(solution_guard, "_warned_degraded", True)
    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text=HINT), LLMResponse(text=HINT),
                             LLMResponse(text=HINT), LLMResponse(text="Good.")])
    run_tutor_turn(session, convo, "plain question", llm,
                   guard_llm=ScriptedLLMClient([_verdict(attempted=False)]))
    run_tutor_turn(session, convo, GUESS, llm, attempt=True,
                   guard_llm=ScriptedLLMClient([_verdict(attempted=False),
                                                _verdict(attempted=False)]))
    run_tutor_turn(session, convo, REAL, llm, attempt=True, guard_llm=_BrokenGuard())
    run_tutor_turn(session, convo, REAL, llm, attempt=True,
                   guard_llm=ScriptedLLMClient([_verdict(attempted=True)]))
    client = _client(session, llm=ScriptedLLMClient([]), guard=ScriptedLLMClient([]))

    body = client.get(f"/api/conversations/{convo.id}").json()

    users = [m for m in body["messages"] if m["role"] == "user"]
    assert [(m["is_attempt"], m["attempt_accepted"]) for m in users] == [
        (False, None),  # an ordinary message
        (True, False),  # rejected: a row with accepted=false
        (True, None),  # unverified: no row, so not judged
        (True, True),  # accepted
    ]
    assert all(m["attempt_accepted"] is None for m in body["messages"] if m["role"] == "tutor")
    assert body["attempt_logged"] is True


def test_sdk_an_allowed_reveal_is_the_reply_even_if_the_model_just_says_see_above(
        session, monkeypatch):
    # Live finding: the reveal tool's text only went back to the model, which replied "I've
    # revealed the full worked solution above", so the learner never saw it.
    convo = _seed(session, attempt_logged=True)
    captured: dict = {}
    real_server = tutor_sdk.create_sdk_mcp_server

    def capture_server(name, tools):
        captured.update({t.name: t for t in tools})
        return real_server(name, tools=tools)

    async def fake_query(prompt, options):
        await captured["reveal_solution"].handler({"text": SECRET})
        yield _FakeResult("I've revealed the full worked solution above.")

    monkeypatch.setattr(tutor_sdk, "create_sdk_mcp_server", capture_server)
    monkeypatch.setattr(tutor_sdk, "ResultMessage", _FakeResult)
    monkeypatch.setattr(tutor_sdk, "query", fake_query)
    monkeypatch.setattr(tutor_sdk, "record_sdk_result", lambda *a, **kw: None)
    result = tutor_sdk.run_tutor_turn_sdk(session, convo, "show me", guard_llm=None)
    assert result.reply == SECRET


def test_sdk_a_blocked_reveal_never_becomes_the_reply(session, monkeypatch):
    convo = _seed(session, attempt_logged=False)
    captured: dict = {}
    real_server = tutor_sdk.create_sdk_mcp_server

    def capture_server(name, tools):
        captured.update({t.name: t for t in tools})
        return real_server(name, tools=tools)

    async def fake_query(prompt, options):
        await captured["reveal_solution"].handler({"text": SECRET})
        yield _FakeResult(HINT)

    monkeypatch.setattr(tutor_sdk, "create_sdk_mcp_server", capture_server)
    monkeypatch.setattr(tutor_sdk, "ResultMessage", _FakeResult)
    monkeypatch.setattr(tutor_sdk, "query", fake_query)
    monkeypatch.setattr(tutor_sdk, "record_sdk_result", lambda *a, **kw: None)
    result = tutor_sdk.run_tutor_turn_sdk(
        session, convo, "show me", guard_llm=ScriptedLLMClient([_verdict(attempted=False)]))
    assert SECRET not in result.reply
