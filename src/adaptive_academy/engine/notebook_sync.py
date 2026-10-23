"""Keep each concept's vault note in step with its notebook (engine/notebook.py).

When a vault is set, a concept's note at `<vault>/Adaptive Academy/<topic>/Concepts/<concept>.md`
carries a managed section between the notebook start and end marker lines. The section is
rebuilt from the database and spliced in. Outside the markers the app changes one thing only:
the value of the frontmatter `verdict:` key, so Dataview queries stay right. Everything else
there is the learner's and is never changed. A missing note is created with frontmatter (title,
concept_id, verdict, load_bearing), a title, a link to the topic hub, and the section; the
verdict and the latest-assessment summary live inside the section. Notes exported before this
change keep their old `**Verdict:**` body line as it was (it is outside the markers); the
current verdict is the one in the section and the frontmatter.

The section's start marker carries a hash of what was written (whitespace-normalised: trailing
spaces, blank-line runs and line endings don't count, and the section is written without
trailing spaces). If the section's text on disk no longer matches (edited in Obsidian), the
sync leaves the note alone and reports it on the vault status.

Names: folders and files use vault.slugify (letters in any script). A name that slugs to nothing
falls back to `topic-<id>` / `concept-<id>`; names that slug alike get an `-<id>` suffix (the
lowest id keeps the plain name); an existing note or folder of this topic or concept under the
name the previous ASCII-only slug gave it is reused rather than copied; and a file whose
frontmatter says it belongs to another topic or concept (`topic_id` / `concept_id`, or for
older notes the title, compared without YAML quotes) is never written: the id-suffixed name is
used instead. Ownership is checked again on the text read under the write lock, so a note
that changed hands after an export planned its path is still left alone. The frontmatter
`verdict:` is edited only inside a closed frontmatter block, and only on a note the app made
(our concept_id, or our title with the adaptive-academy tag). A topic folder is claimed by its hub note, which a sync
creates when it is missing.

Where the vault is: the path the browser last registered (PUT /api/vault/sync, or a note saved
with a vault_path; it must be an Obsidian vault, with a `.obsidian` folder, which may be a
link to a folder), else AA_OBSIDIAN_VAULT_PATH (trusted as set; only .env turns it off). The registered path is process state, like the
browser's own copy of it; the frontend registers it again on load.

When it runs: a commit that adds, changes or deletes a ConceptNote, an Attempt, an Assessment,
or a revealed-solution Message queues that concept (SQLAlchemy session events, so every write
site is covered without each one calling in). Keys are kept until the outermost transaction
ends: a savepoint (every memory.index_* call opens one) neither queues them when it is
released nor drops them when it is rolled back; only the outermost commit queues them, and
only its rollback forgets them. One background thread works
the queue, after the request has answered: a sync never holds up or fails the action that
triggered it. The queue is a capped, de-duplicated set, and each write is bounded
(notebook.SECTION_* caps, a note-size cap). An engine with a StaticPool (the in-memory test
database, one connection shared by every thread) never starts the thread: `drain()` works the
queue in the caller's thread.

Failure handling: a failed sync is logged, traced as a `vault:sync_failed` event, and kept on
`status()` (shown by GET /api/vault/status) until that concept syncs cleanly. The demo topic
is never synced; an explicit export of it still writes it.

File safety: the vault and folders go through vault.safe_vault_dir / safe_child; a note that is
a symlink or not a regular file is refused; the note is read through the vault's no-follow
reader, keeping its line endings; a new note is created exclusively; an existing one is
replaced atomically, and only if it did not change since it was read (else the splice is
redone, up to three times).
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
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, col, select

from adaptive_academy.engine.notebook import (
    MarkerError,
    SectionEdited,
    build_notebook,
    render_notebook_section,
    frontmatter_values,
    set_frontmatter_value,
    splice_notebook_section,
)
from adaptive_academy.engine.vault import (
    EXPORT_FOLDER,
    _concept_verdict_summary,
    _read_text,
    legacy_slugify,
    render_frontmatter,
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
_WRITE_LOCK = threading.RLock()


class UnsafeNote(OSError):
    """The note can't be updated safely (a symlink, not a regular file, too large, not
    UTF-8, or another note's name). It is left as it is."""


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
        text = _read_text(path, vault=vault, limit=NOTE_FILE_MAX_CHARS + 1, errors="strict",
                          newline="")
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


def _write_temp(path: Path, content: str, mode: int) -> str:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".aa-notebook-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode or 0o644)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return tmp


def _replace_if_unchanged(path: Path, content: str, signature: tuple, mode: int) -> bool:
    tmp = _write_temp(path, content, mode)
    try:
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


def write_note_file(vault: Path, path: Path, header: str, section: str,
                    verdict: str | None = None, *, concept: Concept | None = None) -> None:
    """Create the note (header + section) or splice the section into it, and set the
    frontmatter `verdict:` value when the note is one the app made for `concept`.

    With `concept`, ownership is checked again on the text read here, under the write lock:
    a note that became another concept's since its path was chosen is left alone.

    Raises MarkerError (SectionEdited included) or UnsafeNote and leaves the note as it was
    when it can't be done safely; other OSErrors (permissions, a full disk) propagate."""
    with _WRITE_LOCK:
        for _ in range(_WRITE_TRIES):
            existing, signature, mode = _read_existing(vault, path)
            if existing is None:
                if _create_exclusive(path, header.rstrip("\n") + "\n\n" + section + "\n"):
                    return
                continue  # created meanwhile (Obsidian): update it instead
            fm = frontmatter_values(existing)
            if concept is not None and not _owns(fm, "concept_id", concept.id, concept.name):
                raise UnsafeNote(f"{path.name} belongs to another note now, so it was left "
                                 "alone")
            content = splice_notebook_section(existing, section)
            if verdict is not None and (concept is None or _made_by_us(fm, concept)):
                content = set_frontmatter_value(content, "verdict", verdict)
            if content == existing:
                return
            if _replace_if_unchanged(path, content, signature, mode):
                return
    raise UnsafeNote(f"{path.name} kept changing while it was being updated; try again")


# --- names and ownership -----------------------------------------------------------------


def _planned(items: list[tuple[int, str]], fallback: str) -> dict[int, str]:
    """A file or folder name per id: the slug, `<fallback>-<id>` when the slug is empty, and
    an `-<id>` suffix for every name after the first (lowest id) that slugs alike."""
    used: set[str] = set()
    out: dict[int, str] = {}
    for ident, name in sorted(items):
        base = slugify(name) or f"{fallback}-{ident}"
        stem = base
        while stem in used:
            stem = f"{stem}-{ident}"
        used.add(stem)
        out[ident] = stem
    return out


def _candidates(planned: str, ident: int) -> list[str]:
    return [planned] if planned.endswith(f"-{ident}") else [planned, f"{planned}-{ident}"]


def _head_frontmatter(vault: Path, path: Path) -> dict | None:
    """The frontmatter values of an existing note, YAML quotes removed (None when there is
    no file, {} when it has no closed frontmatter block)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise UnsafeNote(f"{path.name} is a link or not a regular file, so it was left alone")
    try:
        text = _read_text(path, vault=vault, limit=8_000, errors="strict")
    except UnicodeError:
        return {}
    return frontmatter_values(text)


def _owns(fm: dict, id_key: str, ident: int, title: str) -> bool:
    """Whether an existing note at our path is this topic's or concept's: its id key says
    so, or (older notes, written before the id) its title does. A note with neither, inside
    the app's own folder, is taken as ours: every note of another concept has one of them.
    Values compare without YAML quotes (Obsidian's Properties editor may add them)."""
    if fm.get(id_key, "").strip():
        return fm[id_key].strip() == str(ident)
    existing = fm.get("title", "").strip()
    return not existing or existing == title.strip()


def _names_us(fm: dict | None, id_key: str, ident: int, title: str) -> bool:
    """Stricter than _owns: the note says it is ours (id, or title), not just "no owner"."""
    if not fm:
        return False
    if fm.get(id_key, "").strip():
        return fm[id_key].strip() == str(ident)
    return fm.get("title", "").strip() == title.strip()


def _made_by_us(fm: dict, concept: Concept) -> bool:
    """A note the app made for this concept: it carries our concept_id, or (exported before
    the id) our title and the adaptive-academy tag. Only then is its `verdict:` the app's."""
    if fm.get("concept_id", "").strip():
        return fm["concept_id"].strip() == str(concept.id)
    return (fm.get("title", "").strip() == concept.name.strip()
            and "adaptive-academy" in fm.get("tags", ""))


def topic_concepts(session: Session, topic_id: int) -> list[Concept]:
    return list(session.exec(
        select(Concept).join(Track, col(Track.id) == Concept.track_id)
        .where(Track.topic_id == topic_id).order_by(Concept.id)).all())


def planned_concept_stems(concepts: list[Concept]) -> dict[int, str]:
    return _planned([(c.id, c.name) for c in concepts], "concept")


def _first_of_title(items: list[tuple[int, str]], ident: int, title: str) -> bool:
    """Whether `ident` is the lowest id among the items with exactly this title (the one
    that keeps the plain name, as in _planned)."""
    same = [i for i, t in items if t.strip() == title.strip()]
    return not same or ident == min(same)


def _adopt(vault: Path, folder: Path, planned: str, name: str, id_key: str, ident: int,
           first_of_title: bool, file_of) -> str | None:  # noqa: ANN001
    """An existing note of this topic or concept to reuse instead of starting a second copy:
    under the planned name when it says it is ours (id, or title), or under the name the
    previous ASCII-only slug gave it (an export made before the slug change).

    The old name is taken on an id match; on a title alone only when the slug really changed
    for this name (else the old name is just the plain name, which belongs to the lowest id)
    and this is the lowest id with that exact title, so two same-named concepts or topics
    never both claim one older note or folder."""
    if _names_us(_head_frontmatter(vault, file_of(folder, planned)), id_key, ident, name):
        return planned
    legacy = legacy_slugify(name)
    if not legacy or legacy == planned:
        return None
    fm = _head_frontmatter(vault, file_of(folder, legacy))
    if not fm:
        return None
    if fm.get(id_key, "").strip():
        return legacy if fm[id_key].strip() == str(ident) else None
    title_only = (fm.get("title", "").strip() == name.strip() and first_of_title
                  and legacy != slugify(name))
    return legacy if title_only else None


def concept_note_path(vault: Path, concepts_dir: Path, concept: Concept, planned: str,
                      siblings: list[Concept] | None = None) -> Path:
    """This concept's note path: an existing note of this concept under the planned name or
    the name the previous slug rules gave it (legacy_slugify, see _adopt), else the planned
    name unless that file is another note's, then the id-suffixed one. Never another
    concept's note (UnsafeNote when both are taken). `siblings`: the topic's concepts, to
    tell which of several same-named ones may take an older note by title."""
    first = _first_of_title([(c.id, c.name) for c in siblings or [concept]], concept.id,
                            concept.name)
    adopted = _adopt(vault, concepts_dir, planned, concept.name, "concept_id", concept.id,
                     first, lambda folder, stem: folder / f"{stem}.md")
    if adopted is not None:
        return concepts_dir / f"{adopted}.md"
    for stem in _candidates(planned, concept.id):
        # Not resolved: a note that is itself a symlink must be seen (and refused) as one.
        path = concepts_dir / f"{stem}.md"
        fm = _head_frontmatter(vault, path)
        if fm is None or _owns(fm, "concept_id", concept.id, concept.name):
            return path
    raise UnsafeNote(f"{planned}.md belongs to another note, so {concept.name} was not written")


def _placeholder_hub(topic: Topic) -> str:
    fm = render_frontmatter({"title": topic.title, "tags": ["adaptive-academy"],
                             "topic_id": topic.id})
    return (f"{fm}\n# {topic.title}\n\nExport this topic from the Vault page in Adaptive "
            "Academy to add its track and concept list here.\n")


def topic_folder(session: Session, vault: Path, topic: Topic, *,
                 create: bool = True) -> tuple[Path, str]:
    """The topic's folder under the export folder and its hub note's name. The hub claims
    the folder: a folder whose hub is another topic's is skipped for the id-suffixed name,
    and a folder without a hub is claimed by creating one. `create=False` only looks: the
    folder a sync would use, with nothing made (it may not exist)."""
    topics = [(t.id, t.title) for t in session.exec(select(Topic)).all()]
    planned = _planned(topics, "topic")[topic.id]
    with _WRITE_LOCK:
        # A folder this topic was exported to under the previous slug rules is kept.
        root = safe_child(vault, EXPORT_FOLDER)
        adopted = _adopt(vault, root, planned, topic.title, "topic_id", topic.id,
                         _first_of_title(topics, topic.id, topic.title),
                         lambda folder, stem: folder / stem / f"{stem}.md")
        if adopted is not None:
            return safe_child(vault, EXPORT_FOLDER, adopted), adopted
        for stem in _candidates(planned, topic.id):
            folder = safe_child(vault, EXPORT_FOLDER, stem)
            hub = folder / f"{stem}.md"
            fm = _head_frontmatter(vault, hub)
            if fm is None:
                if not create:
                    return folder, stem
                folder.mkdir(parents=True, exist_ok=True)
                if not _create_exclusive(hub, _placeholder_hub(topic)):
                    fm = _head_frontmatter(vault, hub) or {}
                    if not _owns(fm, "topic_id", topic.id, topic.title):
                        continue
                return folder, stem
            if _owns(fm, "topic_id", topic.id, topic.title):
                if create:
                    folder.mkdir(parents=True, exist_ok=True)
                return folder, stem
    raise UnsafeNote(f"the folder {planned} belongs to another topic, so {topic.title} was "
                     "not written")


def write_hub_note(vault: Path, folder: Path, stem: str, content: str, *,
                   replace: bool) -> Path:
    """Write the topic's hub note (app-owned: replaced whole on export). Never through a
    symlink."""
    hub = folder / f"{stem}.md"
    with _WRITE_LOCK:
        if _create_exclusive(hub, content) or not replace:
            return hub
        st = os.lstat(hub)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise UnsafeNote(f"{hub.name} is a link or not a regular file, so it was left alone")
        tmp = _write_temp(hub, content, stat.S_IMODE(st.st_mode))
        os.replace(tmp, hub)
    return hub


def render_note_header(concept: Concept, verdict: str, hub_stem: str) -> str:
    """A new concept note's header. Verdict and summary are inside the managed section;
    the frontmatter `verdict:` value is kept current by every sync."""
    fm = render_frontmatter({
        "title": concept.name,
        "tags": ["adaptive-academy", "concept"],
        "concept_id": concept.id,
        "verdict": verdict,
        "load_bearing": "true" if concept.is_load_bearing else "false",
    })
    return f"{fm}\n# {concept.name}\n\nPart of [[{hub_stem}]].\n"


def write_concept_note(session: Session, vault: Path, topic: Topic, concept: Concept, *,
                       path: Path | None = None, hub_stem: str | None = None) -> Path:
    """Write one concept's note into `vault` (a safe_vault_dir result). Returns its path.
    `path` and `hub_stem` come from an export that already resolved them."""
    with _WRITE_LOCK:
        if path is None or hub_stem is None:
            folder, hub_stem = topic_folder(session, vault, topic)
            concepts_dir = safe_child(folder, "Concepts")
            concepts_dir.mkdir(parents=True, exist_ok=True)
            siblings = topic_concepts(session, topic.id)
            planned = planned_concept_stems(siblings)
            path = concept_note_path(vault, concepts_dir, concept,
                                     planned.get(concept.id, f"concept-{concept.id}"), siblings)
        verdict, summary = _concept_verdict_summary(session, concept)
        section = render_notebook_section(build_notebook(session, concept), verdict, summary)
        try:
            write_note_file(vault, path, render_note_header(concept, verdict, hub_stem),
                            section, verdict, concept=concept)
        except OSError as exc:
            exc.note_name = path.name  # problems name the note that was actually checked
            raise
        except MarkerError as exc:
            exc.note_name = path.name
            raise
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


def locked_note(session: Session, concept: Concept) -> str | None:
    """The file name of this concept's vault note when its notebook section was edited in
    Obsidian, so every sync leaves it alone (SectionEdited) until that edit is undone or the
    section deleted; None otherwise (no sync vault, the demo topic, no note yet, or a note a
    sync can update). Only looks: nothing is created or written. A note that can't be read
    counts as not locked; the sync reports its own problems."""
    vault_path = sync_vault_path()
    if not vault_path:
        return None
    try:
        track = session.get(Track, concept.track_id)
        topic = session.get(Topic, track.topic_id) if track else None
        if topic is None or topic.is_demo:
            return None
        vault = safe_vault_dir(vault_path)
        folder, _ = topic_folder(session, vault, topic, create=False)
        concepts_dir = safe_child(folder, "Concepts")
        if not concepts_dir.is_dir():
            return None
        siblings = topic_concepts(session, topic.id)
        planned = planned_concept_stems(siblings).get(concept.id, f"concept-{concept.id}")
        path = concept_note_path(vault, concepts_dir, concept, planned, siblings)
        text, _, _ = _read_existing(vault, path)
    except (OSError, ValueError):
        return None
    if text is None:
        return None
    try:
        splice_notebook_section(text, "")  # the same check a sync makes; the result is unused
    except SectionEdited:
        return path.name
    except MarkerError:
        pass  # markers that don't pair up: another problem, which the sync reports
    return None


def problem_text(exc: BaseException) -> str:
    if isinstance(exc, SectionEdited):
        return ("its notebook section was edited in Obsidian, so it was left alone. Undo that "
                "edit, or delete the whole section with both marker lines, and the next sync "
                "writes it again. Put your own notes outside the section")
    if isinstance(exc, MarkerError):
        return (f"{exc}. Fix or remove the notebook marker lines in Obsidian, and the next "
                "sync rewrites the section")
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
        # (engine, kind, id) -> engine: one entry per row per database, in arrival order.
        self._pending: dict[tuple[Engine, str, int], Engine] = {}
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
                "source": sync_vault_source(),
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
                entry = (bind, *key)
                if entry in self._pending:
                    continue
                if len(self._pending) >= self.max_pending:
                    overflow += 1
                    continue
                self._pending[entry] = bind
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
            entry = next(iter(self._pending))
            bind = self._pending.pop(entry)
            self._busy += 1
            return bind, (entry[1], entry[2])

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
                note = f"{slugify(concept.name) or f'concept-{concept.id}'}.md"
                track = session.get(Track, concept.track_id)
                topic_id = track.topic_id if track else None
                written = sync_concept(session, concept.id, vault_path)
            if written is not None:
                self.note_ok(concept_id)
        except Exception as exc:  # noqa: BLE001 - a sync never fails anything; it reports
            note = getattr(exc, "note_name", note)
            self.record_problem(concept_id, f"Couldn't update {note}: {problem_text(exc)}",
                                topic_id=topic_id, bind=bind)


NOTEBOOK_SYNC = NotebookSync()


def register_vault_path(path: str) -> str:
    """Set where notebooks sync (validated and resolved); "" clears it. Raises ValueError
    for a path that isn't an Obsidian vault (an existing folder with a `.obsidian` folder in
    it), leaving the previous one in place. The browser sends this path, so it is checked
    more strictly than AA_OBSIDIAN_VAULT_PATH, which the person running the app set."""
    path = (path or "").strip()
    resolved = ""
    if path:
        vault = safe_vault_dir(path)
        marker = vault / ".obsidian"
        if not marker.is_dir():  # follows a symlink: a linked .obsidian folder is fine
            raise ValueError(
                f"{vault} is not an Obsidian vault: it has no .obsidian folder. Pick the "
                "vault's top folder, the one you open in Obsidian.")
        resolved = str(vault)
    with NOTEBOOK_SYNC._lock:
        NOTEBOOK_SYNC.path = resolved
    NOTEBOOK_SYNC.clear_problem("vault_path")
    return resolved


def sync_vault_path() -> str:
    return NOTEBOOK_SYNC.path or (settings.obsidian_vault_path or "").strip()


def sync_vault_source() -> str:
    """Where the sync target comes from: "browser" (registered), "env"
    (AA_OBSIDIAN_VAULT_PATH), or "" when notes sync nowhere."""
    if NOTEBOOK_SYNC.path:
        return "browser"
    return "env" if (settings.obsidian_vault_path or "").strip() else ""


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


@event.listens_for(OrmSession, "before_flush")
def _collect_moves(session: OrmSession, _flush_context, _instances) -> None:  # noqa: ANN001
    """A row moved to another concept: the concept it left has a changed notebook too. The
    old value is read from the database when the attribute was set without loading it."""
    try:
        if not sync_vault_path():
            return
        old_ids: set[int] = set()
        for obj in session.dirty:
            if not isinstance(obj, (ConceptNote, Attempt, Assessment)) or obj.id is None:
                continue
            history = sa_inspect(obj).attrs.concept_id.history
            if not history.has_changes():
                continue
            old = [v for v in history.deleted or () if v is not None]
            if not old:
                with session.no_autoflush:
                    row = session.execute(select(type(obj).concept_id)
                                          .where(type(obj).id == obj.id)).first()
                old = [row[0]] if row and row[0] is not None else []
            old_ids.update(old)
        if old_ids:
            session.info.setdefault(_INFO_KEY, set()).update(("concept", i) for i in old_ids)
    except Exception:  # noqa: BLE001 - a sync hook must never break a flush
        logger.exception("vault sync: could not note a moved row")


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
    # after_commit also fires when a SAVEPOINT is released (every memory.index_* call uses
    # begin_nested); the outer transaction is still open then and its rows are not visible
    # to the writer yet. Keep the keys until the outermost commit.
    if session.in_nested_transaction():
        return
    keys = session.info.pop(_INFO_KEY, None)
    if not keys:
        return
    try:
        NOTEBOOK_SYNC.request(session.get_bind(), keys)
    except Exception:  # noqa: BLE001 - a sync hook must never break a commit
        logger.exception("vault sync: could not queue a change")


@event.listens_for(OrmSession, "after_soft_rollback")
def _forget(session: OrmSession, previous_transaction) -> None:  # noqa: ANN001
    # Only when the whole transaction is rolled back. A savepoint rolled back inside it (the
    # embedder's begin_nested in memory.index_text) keeps what the transaction still holds;
    # an extra key only costs a rewrite that finds nothing new.
    if not previous_transaction.nested and previous_transaction.parent is None:
        session.info.pop(_INFO_KEY, None)
