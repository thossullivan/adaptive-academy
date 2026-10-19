"""The bounded trace writer: a batch that hits a lock timeout is logged with its row count,
and usage rows (which are spend records, not just traces) get one bounded retry."""

import logging

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from adaptive_academy.engine.trace_writer import TraceWriter
from adaptive_academy.models import LLMUsage


@pytest.fixture
def file_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'trace.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _row():
    return LLMUsage(backend="anthropic", model="claude-sonnet-5-5", role="reasoning",
                    operation="complete", cost_usd=0.01)


def _locked_n_times(writer: TraceWriter, n: int):
    real = writer._commit_batch
    state = {"left": n, "attempts": 0}

    def flaky(bind, rows):
        state["attempts"] += 1
        if state["left"] > 0:
            state["left"] -= 1
            raise OperationalError("INSERT", {}, Exception("database is locked"))
        real(bind, rows)

    writer._commit_batch = flaky
    return state


def _count(engine) -> int:
    with Session(engine) as s:
        return len(s.exec(select(LLMUsage)).all())


def test_a_retried_batch_survives_one_lock_timeout(file_engine, caplog):
    writer = TraceWriter()
    state = _locked_n_times(writer, 1)
    with caplog.at_level(logging.WARNING):
        assert writer.submit(file_engine, [_row(), _row()], retries=1)
        assert writer.flush(5)
    assert _count(file_engine) == 2
    assert state["attempts"] == 2
    assert writer.dropped == 0 and writer.written == 2
    assert "retrying" in caplog.text


def test_retries_are_bounded_and_the_drop_is_logged_with_its_row_count(file_engine, caplog):
    writer = TraceWriter()
    state = _locked_n_times(writer, 10)
    with caplog.at_level(logging.WARNING):
        writer.submit(file_engine, [_row(), _row(), _row()], retries=5)
        assert writer.flush(5)
    assert _count(file_engine) == 0
    assert state["attempts"] == 1 + TraceWriter.MAX_RETRIES  # bounded, whatever was asked
    assert writer.dropped == 3
    drops = [r for r in caplog.records if "dropped" in r.getMessage()]
    assert drops and drops[-1].levelno == logging.WARNING
    assert "3 rows" in drops[-1].getMessage()


def test_plain_trace_batches_are_not_retried(file_engine):
    writer = TraceWriter()
    state = _locked_n_times(writer, 1)
    writer.submit(file_engine, [_row()])
    assert writer.flush(5)
    assert state["attempts"] == 1 and writer.dropped == 1


def test_usage_rows_ask_for_a_retry(monkeypatch, file_engine):
    from adaptive_academy.llm import usage

    seen = {}

    def fake_submit(bind, rows, *, retries=0):
        seen["retries"] = retries
        return True

    usage.set_usage_bind(file_engine)
    monkeypatch.setattr(usage.TRACE_WRITER, "submit", fake_submit)
    usage.record_usage(backend="anthropic", model="claude-sonnet-5-5", role="reasoning",
                       operation="complete", usage=None)
    assert seen["retries"] == 1
