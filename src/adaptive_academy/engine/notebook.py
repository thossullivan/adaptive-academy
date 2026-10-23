"""Concept notebooks: a concept's notes and work in one place
(docs/superpowers/specs/2026-10-23-concept-notes-design.md).

A notebook is assembled from rows the app already keeps, newest first:

- My notes: the learner's own text (ConceptNote), saved per concept.
- My attempts: Attempt rows with the message text, accepted or not (both are shown, the
  rejected ones marked as such).
- My explanations: graded Assessment rows of EXPLANATION_KINDS, with score and gaps.
  Artifact reviews, source quizzes, roleplays and paper probes are other kinds of evidence
  and stay out.
- Worked solutions: tutor messages marked Message.reveals_solution (the gate allowed them).

This module also renders the notebook as the vault note's managed section and splices it
into a note between START_MARKER and END_MARKER, leaving everything outside the markers as
it was. Pure DB reads and string work: file I/O lives in engine/notebook_sync.py.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, col, select

from adaptive_academy.models import (
    Assessment,
    Attempt,
    Concept,
    ConceptNote,
    Conversation,
    Message,
    Track,
    now_utc,
)

NOTE_MAX_CHARS = 50_000

# Assessment kind -> (label, the page it was made on).
EXPLANATION_KINDS: dict[str, tuple[str, str]] = {
    "self_explanation": ("Self-explanation", "assess"),
    "calibration": ("Calibration", "assess"),
    "teach": ("Teach-back", "teach"),
    "recall": ("Decay check", "retention"),
}

# The start marker as written carries a hash of the section body:
# "<!-- adaptive-academy:notebook:start sha=0123456789abcdef -->". START_MARKER (no hash)
# is the plain form, also recognised.
START_PREFIX = "<!-- adaptive-academy:notebook:start"
START_MARKER = f"{START_PREFIX} -->"
END_MARKER = "<!-- adaptive-academy:notebook:end -->"
_SHA = re.compile(r"\bsha=([0-9a-f]+)\b")

# Bounds on what one vault section holds, so a sync stays small however long the history.
SECTION_ITEMS_PER_PART = 50
SECTION_ITEM_CHARS = 4_000


class NoteTooLong(ValueError):
    def __init__(self, length: int):
        super().__init__(
            f"Your notes are too long to save: {length:,} characters. The limit is "
            f"{NOTE_MAX_CHARS:,} characters.")
        self.length = length


class MarkerError(ValueError):
    """The note's notebook markers don't pair up, so the managed section can't be found."""


class SectionEdited(MarkerError):
    """The managed section was changed by hand since it was written; it is left alone."""


@dataclass
class NotebookItem:
    kind: str  # attempt | explanation | solution
    id: int
    created_at: datetime
    source: str  # the page it was made on: tutor | assess | teach | retention
    text: str
    conversation_id: int | None = None
    accepted: bool | None = None  # attempts only
    assessment_kind: str | None = None  # explanations only
    label: str = ""
    prompt: str = ""
    score: float | None = None
    verdict: str = ""
    gaps: list[str] = field(default_factory=list)


@dataclass
class Notebook:
    concept_id: int
    concept_name: str
    topic_id: int | None
    note_body: str
    note_updated_at: datetime | None
    items: list[NotebookItem]

    def count(self, kind: str) -> int:
        return sum(1 for item in self.items if item.kind == kind)


@dataclass
class NotebookSummary:
    concept_id: int
    name: str
    has_note: bool
    attempts: int
    explanations: int
    solutions: int
    last_activity_at: datetime


def concept_topic_id(session: Session, concept: Concept) -> int | None:
    track = session.get(Track, concept.track_id)
    return track.topic_id if track else None


def _attempts(session: Session, concept_ids: list[int]) -> list[tuple[Attempt, Message]]:
    if not concept_ids:
        return []
    return list(session.exec(
        select(Attempt, Message)
        .join(Message, col(Message.id) == Attempt.message_id)
        .where(col(Attempt.concept_id).in_(concept_ids))
    ).all())


def _explanations(session: Session, concept_ids: list[int]) -> list[Assessment]:
    if not concept_ids:
        return []
    return list(session.exec(
        select(Assessment).where(col(Assessment.concept_id).in_(concept_ids),
                                 col(Assessment.kind).in_(list(EXPLANATION_KINDS)))
    ).all())


def _solutions(session: Session, concept_ids: list[int]) -> list[tuple[Message, int]]:
    if not concept_ids:
        return []
    return list(session.exec(
        select(Message, Conversation.concept_id)
        .join(Conversation, col(Conversation.id) == Message.conversation_id)
        .where(col(Conversation.concept_id).in_(concept_ids),
               col(Message.reveals_solution).is_(True))
    ).all())


def build_notebook(session: Session, concept: Concept) -> Notebook:
    note = session.exec(select(ConceptNote).where(ConceptNote.concept_id == concept.id)).first()
    items: list[NotebookItem] = []
    for attempt, message in _attempts(session, [concept.id]):
        items.append(NotebookItem(
            kind="attempt", id=attempt.id, created_at=attempt.created_at, source="tutor",
            text=message.content, conversation_id=attempt.conversation_id,
            accepted=attempt.accepted))
    for a in _explanations(session, [concept.id]):
        label, source = EXPLANATION_KINDS[a.kind]
        items.append(NotebookItem(
            kind="explanation", id=a.id, created_at=a.created_at, source=source,
            text=a.response, assessment_kind=a.kind, label=label, prompt=a.prompt,
            score=a.score, verdict=a.verdict, gaps=list(a.gaps or [])))
    for message, _concept_id in _solutions(session, [concept.id]):
        items.append(NotebookItem(
            kind="solution", id=message.id, created_at=message.created_at, source="tutor",
            text=message.content, conversation_id=message.conversation_id))
    # Newest first; a tie keeps a fixed order (explanation, solution, attempt; then id).
    rank = {"explanation": 2, "solution": 1, "attempt": 0}
    items.sort(key=lambda i: (i.created_at, rank[i.kind], i.id), reverse=True)
    return Notebook(
        concept_id=concept.id, concept_name=concept.name,
        topic_id=concept_topic_id(session, concept),
        note_body=note.body if note else "",
        note_updated_at=note.updated_at if note else None,
        items=items)


def save_note(session: Session, concept_id: int, body: str) -> ConceptNote:
    """Save the learner's notes on a concept (one row per concept). Commits."""
    if len(body) > NOTE_MAX_CHARS:
        raise NoteTooLong(len(body))
    note = session.exec(select(ConceptNote).where(ConceptNote.concept_id == concept_id)).first()
    if note is None:
        note = ConceptNote(concept_id=concept_id)
    note.body = body
    note.updated_at = now_utc()
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def topic_notebook(session: Session, topic_id: int) -> list[NotebookSummary]:
    """The topic's concepts that have notes or work, latest activity first."""
    concepts = session.exec(
        select(Concept).join(Track, col(Track.id) == Concept.track_id)
        .where(Track.topic_id == topic_id)
    ).all()
    ids = [c.id for c in concepts]
    if not ids:
        return []
    stats: dict[int, dict] = {
        c.id: {"attempts": 0, "explanations": 0, "solutions": 0, "has_note": False,
               "last": None} for c in concepts}

    def touch(cid: int, when: datetime) -> None:
        last = stats[cid]["last"]
        if last is None or when > last:
            stats[cid]["last"] = when

    for note in session.exec(select(ConceptNote).where(col(ConceptNote.concept_id).in_(ids))):
        if note.body.strip():
            stats[note.concept_id]["has_note"] = True
            touch(note.concept_id, note.updated_at)
    for attempt, _message in _attempts(session, ids):
        stats[attempt.concept_id]["attempts"] += 1
        touch(attempt.concept_id, attempt.created_at)
    for a in _explanations(session, ids):
        stats[a.concept_id]["explanations"] += 1
        touch(a.concept_id, a.created_at)
    for message, cid in _solutions(session, ids):
        stats[cid]["solutions"] += 1
        touch(cid, message.created_at)

    rows = [
        NotebookSummary(concept_id=c.id, name=c.name, has_note=s["has_note"],
                        attempts=s["attempts"], explanations=s["explanations"],
                        solutions=s["solutions"], last_activity_at=s["last"])
        for c in concepts if (s := stats[c.id])["last"] is not None
    ]
    rows.sort(key=lambda r: (r.last_activity_at, r.concept_id), reverse=True)
    return rows


# --- the vault note's managed section --------------------------------------------------------

_SOURCE_LABELS = {"tutor": "Tutor", "assess": "Assess", "teach": "Teach",
                  "retention": "Retention"}


def _neutral(text: str) -> str:
    """Learner and model text can't carry a marker line into the section."""
    return (text or "").replace("adaptive-academy:notebook:", "adaptive-academy-notebook-")


def _clip(text: str) -> str:
    text = _neutral(text).strip()
    if len(text) <= SECTION_ITEM_CHARS:
        return text
    return text[:SECTION_ITEM_CHARS].rstrip() + "\n\n(Shortened. The full text is in Adaptive Academy.)"


def _quote(text: str) -> str:
    return "\n".join(f"> {line}".rstrip() for line in (_clip(text) or "(empty)").splitlines())


def _day(when: datetime) -> str:
    return when.strftime("%Y-%m-%d")


def _part(title: str, items: list[NotebookItem], render) -> list[str]:  # noqa: ANN001
    out = [f"### {title}", ""]
    if not items:
        out += ["Nothing yet.", ""]
        return out
    for item in items[:SECTION_ITEMS_PER_PART]:
        out += render(item)
    older = len(items) - SECTION_ITEMS_PER_PART
    if older > 0:
        out += [f"{older} older item{'s' if older != 1 else ''} in Adaptive Academy.", ""]
    return out


def _attempt_lines(item: NotebookItem) -> list[str]:
    state = "accepted" if item.accepted else "not accepted"
    return [f"**{_day(item.created_at)}** · Tutor · {state}", "", _quote(item.text), ""]


def _explanation_lines(item: NotebookItem) -> list[str]:
    score = f" · score {item.score:.2f}" if item.score is not None else ""
    source = _SOURCE_LABELS.get(item.source, item.source)
    out = [f"**{_day(item.created_at)}** · {item.label}{score} · {source}", ""]
    if item.prompt.strip():
        out += [f"Prompt: {_neutral(' '.join(item.prompt.split()))[:400]}", ""]
    out += [_quote(item.text), ""]
    if item.verdict.strip():
        out += [f"Verdict: {_neutral(' '.join(item.verdict.split()))}", ""]
    if item.gaps:
        out += ["Gaps: " + "; ".join(_neutral(g) for g in item.gaps), ""]
    return out


def _solution_lines(item: NotebookItem) -> list[str]:
    return [f"**{_day(item.created_at)}** · Tutor", "", _quote(item.text), ""]


def section_digest(body: str) -> str:
    """Short hash of a section's body (between the marker lines), line endings normalised."""
    norm = body.replace("\r\n", "\n").replace("\r", "\n")
    if norm.endswith("\n"):
        norm = norm[:-1]
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def render_notebook_section(nb: Notebook, verdict: str, summary: str = "") -> str:
    """The managed section, markers included (no trailing newline). The start marker
    carries a hash of the body, so a later sync can tell whether it was edited by hand."""
    by_kind = {k: [i for i in nb.items if i.kind == k]
               for k in ("attempt", "explanation", "solution")}
    lines = [
        "## Notebook",
        "",
        f"**Verdict:** {verdict}",
        "",
    ]
    if summary.strip():
        lines += [_neutral(summary.strip()), ""]
    lines += [
        "Adaptive Academy writes this section and rewrites it on every sync. Write your own "
        "notes above or below it, not inside it: once this section is edited here, syncing "
        "stops for this note until the edit is undone or the section is deleted. Edit My "
        "notes in the app.",
        "",
        "### My notes",
        "",
        _neutral(nb.note_body).strip() or "Nothing yet.",
        "",
    ]
    lines += _part("My attempts", by_kind["attempt"], _attempt_lines)
    lines += _part("My explanations", by_kind["explanation"], _explanation_lines)
    lines += _part("Worked solutions", by_kind["solution"], _solution_lines)
    while lines and lines[-1] == "":
        lines.pop()
    body = "\n".join(lines)
    return f"{START_PREFIX} sha={section_digest(body)} -->\n{body}\n{END_MARKER}"


def _eol(text: str) -> str:
    """The note's own line ending (the first one found), "\n" when it has none."""
    for i, ch in enumerate(text):
        if ch == "\r":
            return "\r\n" if text[i + 1:i + 2] == "\n" else "\r"
        if ch == "\n":
            return "\n"
    return "\n"


def _is_start(line: str) -> bool:
    s = line.strip()
    return s == START_MARKER or (s.startswith(START_PREFIX + " ") and s.endswith("-->"))


def splice_notebook_section(text: str, section: str) -> str:
    """Put `section` (rendered with "\n") into the note `text`, changing nothing outside
    the markers. The section takes the note's own line ending.

    - No markers: the section is appended after a blank line.
    - One start..end pair: the lines from start to end are replaced, unless the section
      was edited by hand since it was written (its body no longer matches the hash in the
      start marker): SectionEdited, and the caller leaves the note alone.
    - Anything else (a start without an end, an end first, nested starts, or more than one
      section, which may be a copy the learner pasted): MarkerError, and the caller leaves
      the note alone rather than guess what is the learner's.
    Markers are matched as whole lines, ignoring surrounding whitespace.
    """
    eol = _eol(text)
    section = section.replace("\n", eol)
    lines = text.splitlines(keepends=True)
    marks = []
    for i, line in enumerate(lines):
        if _is_start(line):
            marks.append((i, "start"))
        elif line.strip() == END_MARKER:
            marks.append((i, "end"))
    if not marks:
        if not text:
            return section + eol
        if text.endswith(eol + eol):
            sep = ""
        elif text.endswith(("\n", "\r")):
            sep = eol
        else:
            sep = eol + eol
        return text + sep + section + eol
    kinds = [m for _, m in marks]
    if kinds != ["start", "end"]:
        several = kinds == ["start", "end"] * (len(kinds) // 2)
        raise MarkerError("there is more than one notebook section" if several
                          else "the notebook markers don't pair up")
    (s, _), (e, _) = marks
    match = _SHA.search(lines[s])
    if match and section_digest("".join(lines[s + 1:e])) != match.group(1):
        raise SectionEdited("the notebook section was edited in the note")
    ending = lines[e][len(lines[e].rstrip("\r\n")):]
    return "".join(lines[:s]) + section + ending + "".join(lines[e + 1:])


_FRONTMATTER_KEY = re.compile(r"^(?P<key>[A-Za-z0-9_-]+)\s*:")


def set_frontmatter_value(text: str, key: str, value: str) -> str:
    """Set an existing `key:` line's value in the note's YAML frontmatter, and nothing else:
    no frontmatter, or no such key, leaves the text as it was."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return text
    for i in range(1, len(lines)):
        bare = lines[i].rstrip("\r\n")
        if bare in ("---", "..."):
            return text
        m = _FRONTMATTER_KEY.match(bare)
        if m and m.group("key") == key:
            ending = lines[i][len(bare):]
            lines[i] = f"{key}: {value}{ending}"
            return "".join(lines)
    return text
