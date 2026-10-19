"""One bounded background writer for best-effort trace rows.

Read endpoints (memory search) log an `AgentEvent` trace. That row must never make
the request wait on SQLite's write lock — a long agent run can hold it for a minute —
and it must never cost a pooled connection per request: a thread per search could
park up to the pool's capacity on the busy timeout and starve the next read (Codex
review of PR #7, round 2). So there is exactly one writer thread, fed by a capped
queue; when the queue is full the trace is dropped and counted, never the request.

LLM usage rows (llm/usage.py) ride the same writer for the same reasons: they are
best-effort and must never hold a request on the write lock. They are also the record the
daily spending limit counts, so a usage batch that hits a lock timeout gets one bounded
retry (MAX_RETRIES caps whatever a caller asks for); a plain trace batch is dropped at once.
Every drop is logged at WARNING with its row count.

Engines with a StaticPool (the in-memory test fixture) share one connection across
threads, so the writer runs inline there to keep tests deterministic.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Sequence

from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

logger = logging.getLogger(__name__)

TRACE_QUEUE_MAX = 256


class TraceWriter:
    # Upper bound on per-batch retries after a lock timeout. Each attempt can wait the
    # engine's full busy timeout, so this also bounds how long one batch can stall the queue.
    MAX_RETRIES = 1

    def __init__(self, maxsize: int = TRACE_QUEUE_MAX):
        self._queue: queue.Queue[tuple[Engine, list[SQLModel], int]] = queue.Queue(maxsize)
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        # Inline (StaticPool) writes share one connection; callers on a thread pool (research
        # fan-out recording LLM usage) must not interleave on it.
        self._inline_lock = threading.Lock()
        self.dropped = 0
        self.written = 0

    def submit(self, bind: Engine, rows: Sequence[SQLModel], *, retries: int = 0) -> bool:
        """Queue `rows` (already expunged/transient). Returns False if dropped.

        `retries`: extra attempts after a lock timeout (capped at MAX_RETRIES).
        """
        rows = list(rows)
        if not rows:
            return True
        retries = min(max(retries, 0), self.MAX_RETRIES)
        if isinstance(bind.pool, StaticPool):
            with self._inline_lock:
                self._write(bind, rows, retries)
            return True
        try:
            self._queue.put_nowait((bind, rows, retries))
        except queue.Full:
            self.dropped += len(rows)
            logger.warning("trace queue full; dropped %d trace row(s)", len(rows))
            return False
        self._ensure_thread()
        return True

    def flush(self, timeout: float = 10.0) -> bool:
        """Block until every queued batch is written (tests). False on timeout."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.01)
        return True

    def _ensure_thread(self) -> None:
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="trace-writer", daemon=True
                )
                self._thread.start()

    def _run(self) -> None:
        while True:
            bind, rows, retries = self._queue.get()
            try:
                self._write(bind, rows, retries)
            except Exception:  # noqa: BLE001 - the sole writer must survive anything
                self.dropped += len(rows)
                logger.exception("trace writer: unexpected failure; %d row(s) dropped", len(rows))
            finally:
                self._queue.task_done()

    def _commit_batch(self, bind: Engine, rows: list[SQLModel]) -> None:
        with Session(bind) as session:
            session.add_all(rows)
            session.commit()

    def _write(self, bind: Engine, rows: list[SQLModel], retries: int = 0) -> None:
        """Write one batch; a failure of any kind drops the batch, never propagates.

        An OperationalError (typically "database is locked" after the busy timeout) is
        retried up to `retries` times; anything else drops the batch immediately.
        """
        attempts = 1 + min(max(retries, 0), self.MAX_RETRIES)
        for attempt in range(1, attempts + 1):
            try:
                self._commit_batch(bind, rows)
            except OperationalError as exc:
                if attempt < attempts:
                    logger.warning("trace write failed (%d rows), retrying: %s",
                                   len(rows), exc)
                    continue
                self.dropped += len(rows)
                logger.warning("trace dropped (%d rows) after %d attempt(s): %s",
                               len(rows), attempts, exc)
                return
            except Exception:  # noqa: BLE001 - trace rows are best-effort by contract
                self.dropped += len(rows)
                logger.exception("trace dropped (%d rows): unexpected failure", len(rows))
                return
            self.written += len(rows)
            return

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


TRACE_WRITER = TraceWriter()
