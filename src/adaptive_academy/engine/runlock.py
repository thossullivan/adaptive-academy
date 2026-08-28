"""Process-level guards for long agent runs.

Engine paths commit before every researcher/LLM call so no SQLite write lock spans a
network round trip (F5). That also removed an accidental serialization: two requests
for the same long run used to collide on the lock, and the second failed. The guard
here makes that explicit — the second request is refused with `RunInProgress` before
any paid work starts. One lock per run key (e.g. ``revision:3``, ``research:7``).

The app runs as one uvicorn process, so a threading lock is the right scope.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class RunInProgress(RuntimeError):
    """The same long run is already active in this process."""


_LOCKS: dict[str, threading.Lock] = {}
_REGISTRY = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _REGISTRY:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


@contextmanager
def exclusive_run(key: str) -> Iterator[None]:
    """Hold the run guard for `key`; refuse immediately if it is already held."""
    lock = _lock_for(key)
    if not lock.acquire(blocking=False):
        raise RunInProgress(f"{key} is already running; wait for it to finish")
    try:
        yield
    finally:
        lock.release()
