"""Keep each concept's vault note in step with its notebook (engine/notebook.py).

When a vault is set, a concept's note at `<vault>/Adaptive Academy/<topic>/Concepts/<concept>.md`
carries a managed section between notebook.START_MARKER and notebook.END_MARKER. The section is
rebuilt from the database and spliced in; everything outside the markers is the learner's and
is never changed. A missing note is created with the usual header (frontmatter, verdict, link
to the topic hub) and the section.

Where the vault is: the path the browser last registered (PUT /api/vault/sync, or a note saved
with a vault_path), else AA_OBSIDIAN_VAULT_PATH. The registered path is process state, like
the browser's own copy of it; the frontend registers it again on load.

When it runs: a commit that adds or changes a ConceptNote, an Attempt, an Assessment, or a
revealed-solution Message queues that concept (SQLAlchemy session events, so every write site
is covered without each one calling in). One background thread works the queue, after the
request has answered: a sync never holds up or fails the action that triggered it. The queue
is a capped, de-duplicated set, and each write is bounded (notebook.SECTION_* caps, a note-size
cap). An engine with a StaticPool (the in-memory test database, one connection shared by
every thread) never starts the thread: `drain()` works the queue in the caller's thread.

Failure handling: a failed sync is logged, traced as a `vault:sync_failed` event, and kept on
`status()` (shown by GET /api/vault/status) until that concept syncs cleanly. The demo topic
is never synced; an explicit export of it still writes it.

File safety: the vault and folders go through vault.safe_vault_dir / safe_child; a note that is
a symlink or not a regular file is refused; the note is read through the vault's no-follow
reader; a new note is created exclusively; an existing one is replaced atomically, and only if
it did not change since it was read (else the splice is redone, up to three times).
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from adaptive_academy.engine.notebook import (
    MarkerError,
    build_notebook,
    render_notebook_section,
    splice_notebook_section,
)
from adaptive_academy.engine.vault import (
    EXPORT_FOLDER,
    _concept_verdict_summary,
    _read_text,
    render_concept_note,
    safe_child,
    safe_vault_dir,
    slugify,
)
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Attempt,
    Concept,
    ConceptNote,
    Conversation,
    Message,
    Topic,
    Track,
    now_utc,
)
from adaptive_academy.settings import settings

logger = logging.getLogger(__name__)

NOTE_FILE_MAX_CHARS = 1_000_000
_WRITE_TRIES = 3
# One writer at a time for concept notes (the sync thread and an export can overlap).
_WRITE_LOCK = threading.Lock()


class UnsafeNote(OSError):
    """The note can't be updated safely (a symlink, not a regular file, too large, or not
    UTF-8). It is left as it is."""


# --- writing one note ----------------------------------------------------------------------


def _signature(st: os.stat_result) -> tuple[int, int, int]:
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _read_existing(vault: Path, path: Path) -> tuple[str | None, tuple | None, int]:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None, None, 0
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise UnsafeNote(f"{path.name} is a link or not a regular file, so it was left alone")
    try:
        text = _read_text(path, vault=vault, limit=NOTE_FILE_MAX_CHARS + 1, errors="strict")
    except UnicodeError as exc:
        raise UnsafeNote(f"{path.name} is not UTF-8 text, so it was left alone") from exc
    if len(text) > NOTE_FILE_MAX_CHARS:
        raise UnsafeNote(f"{path.name} is too large to update safely, so it was left alone")
    return text, _signature(st), stat.S_IMODE(st.st_mode)


def _create_exclusive(path: Path, content: str) -> bool:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    return True


def _replace_if_unchanged(path: Path, content: str, signature: tuple, mode: int) -> bool:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".aa-notebook-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode or 0o644)
        try:
            current = os.lstat(path)
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(current.st_mode) or _signature(current) != signature:
            return False
        os.replace(tmp, path)
        tmp = ""
        return True
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def write_note_file(vault: Path, path: Path, header: str, section: str) -> None:
    """Create the note (header + section) or splice the section into it.

    Raises MarkerError or UnsafeNote and leaves the note as it was when it can't be done
    safely; other OSErrors (permissions, a full disk) propagate."""
    with _WRITE_LOCK:
        for _ in range(_WRITE_TRIES):
            existing, signature, mode = _read_existing(vault, path)
            if existing is None:
                if _create_exclusive(path, header.rstrip("\n") + "\n\n" + section + "\n"):
                    return
                continue  # created meanwhile (Obsidian): update it instead
            content = splice_notebook_section(existing, section)
            if content == existing:
                return
            if _replace_if_unchanged(path, content, signature, mode):
                return
    raise UnsafeNote(f"{path.name} kept changing while it was being updated; try again")


def write_concept_note(session: Session, vault: Path, topic: Topic, concept: Concept) -> Path:
    """Write one concept's note into `vault` (a safe_vault_dir result). Returns its path."""
    topic_slug = slugify(topic.title)
    concepts_dir = safe_child(vault, EXPORT_FOLDER, topic_slug, "Concepts")
    concepts_dir.mkdir(parents=True, exist_ok=True)
    # Not resolved: a note that is itself a symlink must be seen (and refused) as one.
    path = concepts_dir / f"{slugify(concept.name)}.md"
    verdict, summary = _concept_verdict_summary(session, concept)
    header = render_concept_note(concept.name, verdict, concept.is_load_bearing, summary,
                                 topic_slug)
    section = render_notebook_section(build_notebook(session, concept), verdict)
    write_note_file(vault, path, header, section)
    return path


def sync_concept(session: Session, concept_id: int, vault_path: str) -> Path | None:
    """Bring one concept's vault note up to date. None when there is nothing to write (no
    such concept, or a demo topic). Raises on a vault or note problem."""
    concept = session.get(Concept, concept_id)
    if concept is None:
        return None
    track = session.get(Track, concept.track_id)
    topic = session.get(Topic, track.topic_id) if track else None
    if topic is None or topic.is_demo:
        return None
    vault = safe_vault_dir(vault_path)
    return write_concept_note(session, vault, topic, concept)


def problem_text(exc: BaseException) -> str:
    if isinstance(exc, MarkerError):
        return ("its notebook markers don't pair up. Fix or remove them in Obsidian, and the "
                "next sync rewrites the section")
    if isinstance(exc, UnsafeNote):
        return str(exc)
    if isinstance(exc, OSError) and exc.strerror:
        return f"{exc.strerror} ({exc.filename})" if exc.filename else exc.strerror
    return str(exc) or type(exc).__name__


# --- the queue -------------------------------------------------------------------------------


class NotebookSync:
    """One background writer for vault notes, fed by a capped, de-duplicated queue."""

    max_pending = 500

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._pending: dict[tuple[str, int], Engine] = {}
        self._busy = 0
        self._thread: threading.Thread | None = None
        self.path = ""
        self._last_ok: datetime | None = None
        self._problems: dict[object, tuple[str, datetime]] = {}
        self._dropped = 0

    def reset(self) -> None:
        """Forget the registered path, the queue, and the status (tests)."""
        with self._lock:
            self._pending.clear()
            self.path = ""
            self._last_ok = None
            self._problems.clear()
            self._dropped = 0

    # status --------------------------------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            latest = max(self._problems.values(), key=lambda p: p[1], default=None)
            return {
                "path": sync_vault_path(),
                "last_synced_at": self._last_ok,
                "last_error": latest[0] if latest else "",
                "last_error_at": latest[1] if latest else None,
                "problems": len(self._problems),
                "pending": len(self._pending) + self._busy,
                "dropped": self._dropped,
            }

    def note_ok(self, concept_id: int | None = None) -> None:
        with self._lock:
            self._last_ok = now_utc()
            if concept_id is not None:
                self._problems.pop(concept_id, None)

    def record_problem(self, key: object, message: str, *, topic_id: int | None = None,
                       bind: Engine | None = None) -> None:
        """Keep a problem on the status, log it, and trace it (best effort, never raises)."""
        logger.warning("vault sync: %s", message)
        with self._lock:
            self._problems[key] = (message, now_utc())
        if topic_id is None or bind is None:
            return
        try:
            from adaptive_academy.engine.trace_writer import TRACE_WRITER

            TRACE_WRITER.submit(bind, [AgentEvent(topic_id=topic_id, kind="vault:sync_failed",
                                                  detail=message[:500])])
        except Exception:  # noqa: BLE001 - tracing a failure must not fail anything
            logger.exception("vault sync: could not trace a failure")

    def clear_problem(self, key: object) -> None:
        with self._lock:
            self._problems.pop(key, None)

    # queue ---------------------------------------------------------------------------------

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def request(self, bind: Engine, keys: set[tuple[str, int]]) -> None:
        if not keys or not sync_vault_path():
            return
        inline = isinstance(getattr(bind, "pool", None), StaticPool)
        overflow = 0
        with self._lock:
            for key in sorted(keys):
                if key in self._pending:
                    continue
                if len(self._pending) >= self.max_pending:
                    overflow += 1
                    continue
                self._pending[key] = bind
            self._dropped += overflow
            if not inline:
                self._wake.notify()
        if overflow:
            self.record_problem(
                "queue", f"The vault sync queue is full, so {overflow} note update(s) were "
                "skipped. Export the topic from the Vault page to bring every note up to date.")
        if not inline:
            self._ensure_thread()

    def drain(self) -> int:
        """Work the whole queue in this thread. Returns how many entries it handled."""
        done = 0
        while (job := self._take()) is not None:
            try:
                self._process(*job)
            finally:
                with self._lock:
                    self._busy -= 1
            done += 1
        return done

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until the queue is empty and nothing is being written (tests)."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if not self._pending and not self._busy:
                    return True
            if time.monotonic() > deadline:
                return False
            time.sleep(0.01)

    def _take(self) -> tuple[Engine, tuple[str, int]] | None:
        with self._lock:
            if not self._pending:
                return None
            key = next(iter(self._pending))
            bind = self._pending.pop(key)
            self._busy += 1
            return bind, key

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="notebook-sync",
                                                daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                while not self._pending:
                    self._wake.wait()
            job = self._take()
            if job is None:
                continue
            try:
                self._process(*job)
            except Exception:  # noqa: BLE001 - the sole writer must survive anything
                logger.exception("vault sync: unexpected failure")
            finally:
                with self._lock:
                    self._busy -= 1

    def _process(self, bind: Engine, key: tuple[str, int]) -> None:
        vault_path = sync_vault_path()
        if not vault_path:
            return
        concept_id: int | None = None
        topic_id: int | None = None
        note = "the concept note"
        try:
            with Session(bind) as session:
                kind, ident = key
                if kind == "conversation":
                    convo = session.get(Conversation, ident)
                    concept_id = convo.concept_id if convo else None
                else:
                    concept_id = ident
                concept = session.get(Concept, concept_id) if concept_id is not None else None
                if concept is None:
                    return
                note = f"{slugify(concept.name)}.md"
                track = session.get(Track, concept.track_id)
                topic_id = track.topic_id if track else None
                written = sync_concept(session, concept.id, vault_path)
            if written is not None:
                self.note_ok(concept_id)
        except Exception as exc:  # noqa: BLE001 - a sync never fails anything; it reports
            self.record_problem(concept_id, f"Couldn't update {note}: {problem_text(exc)}",
                                topic_id=topic_id, bind=bind)


NOTEBOOK_SYNC = NotebookSync()


def register_vault_path(path: str) -> str:
    """Set where notebooks sync (validated and resolved); "" clears it. Raises ValueError
    for a path that isn't an existing folder, leaving the previous one in place."""
    path = (path or "").strip()
    resolved = str(safe_vault_dir(path)) if path else ""
    with NOTEBOOK_SYNC._lock:
        NOTEBOOK_SYNC.path = resolved
    NOTEBOOK_SYNC.clear_problem("vault_path")
    return resolved


def sync_vault_path() -> str:
    return NOTEBOOK_SYNC.path or (settings.obsidian_vault_path or "").strip()


# --- write triggers --------------------------------------------------------------------------

_INFO_KEY = "aa_notebook_sync"


def _touched(session: OrmSession) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, (ConceptNote, Attempt, Assessment)):
            if obj.concept_id is not None:
                keys.add(("concept", obj.concept_id))
        elif isinstance(obj, Message) and obj.reveals_solution:
            if obj.conversation_id is not None:
                keys.add(("conversation", obj.conversation_id))
    return keys


@event.listens_for(OrmSession, "after_flush")
def _collect(session: OrmSession, _flush_context) -> None:  # noqa: ANN001
    try:
        if not sync_vault_path():
            return
        keys = _touched(session)
        if keys:
            session.info.setdefault(_INFO_KEY, set()).update(keys)
    except Exception:  # noqa: BLE001 - a sync hook must never break a flush
        logger.exception("vault sync: could not note a change")


@event.listens_for(OrmSession, "after_commit")
def _queue(session: OrmSession) -> None:
    keys = session.info.pop(_INFO_KEY, None)
    if not keys:
        return
    try:
        NOTEBOOK_SYNC.request(session.get_bind(), keys)
    except Exception:  # noqa: BLE001 - a sync hook must never break a commit
        logger.exception("vault sync: could not queue a change")


@event.listens_for(OrmSession, "after_rollback")
def _forget(session: OrmSession) -> None:
    session.info.pop(_INFO_KEY, None)
