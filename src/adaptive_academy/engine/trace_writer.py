"""One bounded background writer for best-effort trace rows.

Read endpoints (memory search) log an `AgentEvent` trace. That row must never make
the request wait on SQLite's write lock — a long agent run can hold it for a minute —
and it must never cost a pooled connection per request: a thread per search could
park up to the pool's capacity on the busy timeout and starve the next read (Codex
review of PR #7, round 2). So there is exactly one writer thread, fed by a capped
queue; when the queue is full the trace is dropped and counted, never the request.

LLM usage rows (llm/usage.py) ride the same writer for the same reasons: they are
best-effort and must never hold a request on the write lock.

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
    def __init__(self, maxsize: int = TRACE_QUEUE_MAX):
        self._queue: queue.Queue[tuple[Engine, list[SQLModel]]] = queue.Queue(maxsize)
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        # Inline (StaticPool) writes share one connection; callers on a thread pool (research
        # fan-out recording LLM usage) must not interleave on it.
        self._inline_lock = threading.Lock()
        self.dropped = 0
        self.written = 0

    def submit(self, bind: Engine, rows: Sequence[SQLModel]) -> bool:
        """Queue `rows` (already expunged/transient). Returns False if dropped."""
        rows = list(rows)
        if not rows:
            return True
        if isinstance(bind.pool, StaticPool):
            with self._inline_lock:
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
            except Exception:  # noqa: BLE001 - the sole writer must survive anything
                self.dropped += len(rows)
                logger.exception("trace writer: unexpected failure; %d row(s) dropped", len(rows))
            finally:
                self._queue.task_done()

    def _write(self, bind: Engine, rows: list[SQLModel]) -> None:
        """Write one batch; a failure of any kind drops the batch, never propagates."""
        try:
            with Session(bind) as session:
                session.add_all(rows)
                session.commit()
            self.written += len(rows)
        except OperationalError as exc:
            self.dropped += len(rows)
            logger.warning("trace dropped (%d rows): %s", len(rows), exc)
        except Exception:  # noqa: BLE001 - trace rows are best-effort by contract
            self.dropped += len(rows)
            logger.exception("trace dropped (%d rows): unexpected failure", len(rows))

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


TRACE_WRITER = TraceWriter()
