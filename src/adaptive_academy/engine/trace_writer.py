"""One bounded background writer for best-effort trace rows.

Read endpoints (memory search) log an `AgentEvent` trace. That row must never make
the request wait on SQLite's write lock — a long agent run can hold it for a minute —
and it must never cost a pooled connection per request: a thread per search could
park up to the pool's capacity on the busy timeout and starve the next read (Codex
review of PR #7, round 2). So there is exactly one writer thread, fed by a capped
queue; when the queue is full the trace is dropped and counted, never the request.

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
from sqlmodel import Session

from adaptive_academy.models import AgentEvent

logger = logging.getLogger(__name__)

TRACE_QUEUE_MAX = 256


class TraceWriter:
    def __init__(self, maxsize: int = TRACE_QUEUE_MAX):
        self._queue: queue.Queue[tuple[Engine, list[AgentEvent]]] = queue.Queue(maxsize)
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self.dropped = 0
        self.written = 0

    def submit(self, bind: Engine, rows: Sequence[AgentEvent]) -> bool:
        """Queue `rows` (already expunged/transient). Returns False if dropped."""
        rows = list(rows)
        if not rows:
            return True
        if isinstance(bind.pool, StaticPool):
            self._write(bind, rows)
            return True
        try:
            self._queue.put_nowait((bind, rows))
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
            bind, rows = self._queue.get()
            try:
                self._write(bind, rows)
            finally:
                self._queue.task_done()

    def _write(self, bind: Engine, rows: list[AgentEvent]) -> None:
        try:
            with Session(bind) as session:
                session.add_all(rows)
                session.commit()
            self.written += len(rows)
        except OperationalError as exc:
            self.dropped += len(rows)
            logger.warning("trace dropped (%d rows): %s", len(rows), exc)


TRACE_WRITER = TraceWriter()
