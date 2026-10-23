"""Concept notebooks (docs/superpowers/specs/2026-10-23-concept-notes-design.md).

The notebook gathers a concept's notes and work in one place: My notes (ConceptNote), the
learner's attempts (Attempt rows, accepted or not), graded explanations by kind, and worked
solutions the tutor revealed (Message.reveals_solution). When a vault is set, each concept's
Markdown note carries a managed section between fixed markers, rewritten from the database;
everything outside the markers is the learner's and is never changed. All file I/O uses
tmp_path; no model is called.
"""

import os
import shutil
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from adaptive_academy.engine import notebook_sync
from adaptive_academy.engine.notebook import (
    END_MARKER,
    NOTE_MAX_CHARS,
    START_MARKER,
    START_PREFIX,
    MarkerError,
    NoteTooLong,
    SectionEdited,
    build_notebook,
    render_notebook_section,
    save_note,
    splice_notebook_section,
    topic_notebook,
)
from adaptive_academy.engine.notebook_sync import NOTEBOOK_SYNC, sync_concept
from adaptive_academy.engine.vault import EXPORT_FOLDER, export_vault, ingest_vault, reindex_vault
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Attempt,
    Concept,
    ConceptNote,
    Conversation,
    KnowledgeEstimate,
    Message,
    SourceDoc,
    Topic,
    Track,
)

T0 = datetime(2026, 10, 20, 9, 0)


def _seed(session, title="Build LLMs", *, demo=False):
    topic = Topic(title=title, is_demo=demo)
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="Self-Attention", is_load_bearing=True)
    other = Concept(track_id=track.id, name="Softmax")
    session.add(concept)
    session.add(other)
    session.commit()
    return topic, concept, other


def _convo(session, topic, concept, *, at=T0):
    convo = Conversation(topic_id=topic.id, concept_id=concept.id, created_at=at)
    session.add(convo)
    session.commit()
    return convo


def _attempt(session, convo, text, *, accepted, at):
    m = Message(conversation_id=convo.id, role="user", content=text, is_attempt=True,
                created_at=at)
    session.add(m)
    session.flush()
    session.add(Attempt(conversation_id=convo.id, concept_id=convo.concept_id, message_id=m.id,
                        accepted=accepted, created_at=at))
    session.commit()
    return m


def _note_path(vault, topic_slug="build-llms", concept_slug="self-attention"):
    return vault / EXPORT_FOLDER / topic_slug / "Concepts" / f"{concept_slug}.md"


@pytest.fixture
def vault_sync(tmp_path):
    """A registered sync vault, reset afterwards (the sync target is process state)."""
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    NOTEBOOK_SYNC.reset()
    notebook_sync.register_vault_path(str(vault))
    yield vault
    NOTEBOOK_SYNC.reset()


# --- assembly -------------------------------------------------------------------------------


def test_notebook_gathers_every_source_newest_first(session):
    topic, concept, other = _seed(session)
    convo = _convo(session, topic, concept)
    _attempt(session, convo, "guess 42", accepted=False, at=T0 + timedelta(minutes=1))
    _attempt(session, convo, "divide by sqrt(d_k) since variance grows", accepted=True,
             at=T0 + timedelta(minutes=2))
    session.add(Message(conversation_id=convo.id, role="tutor", content="A hint, not a reveal.",
                        created_at=T0 + timedelta(minutes=2, seconds=30)))
    session.add(Message(conversation_id=convo.id, role="tutor", content="Worked: softmax(QK^T)",
                        reveals_solution=True, created_at=T0 + timedelta(minutes=3)))
    for i, kind in enumerate(["self_explanation", "calibration", "teach", "recall",
                              "artifact_review", "source_quiz"]):
        session.add(Assessment(concept_id=concept.id, kind=kind, prompt=f"p-{kind}",
                               response=f"r-{kind}", verdict=f"v-{kind}", score=0.5 + i / 20,
                               gaps=[f"gap-{kind}"], created_at=T0 + timedelta(hours=1 + i)))
    # Another concept's work never leaks in.
    session.add(Assessment(concept_id=other.id, kind="self_explanation", prompt="x",
                           created_at=T0 + timedelta(days=1)))
    session.add(ConceptNote(concept_id=concept.id, body="My own words.",
                            updated_at=T0 + timedelta(days=2)))
    session.commit()

    nb = build_notebook(session, concept)

    assert nb.concept_id == concept.id and nb.topic_id == topic.id
    assert nb.note_body == "My own words."
    kinds = [(i.kind, i.assessment_kind or "") for i in nb.items]
    assert kinds == [
        ("explanation", "recall"),
        ("explanation", "teach"),
        ("explanation", "calibration"),
        ("explanation", "self_explanation"),
        ("solution", ""),
        ("attempt", ""),
        ("attempt", ""),
    ]
    first_attempt, second_attempt = nb.items[-1], nb.items[-2]
    assert first_attempt.accepted is False and first_attempt.text == "guess 42"
    assert second_attempt.accepted is True
    assert first_attempt.conversation_id == convo.id and first_attempt.source == "tutor"
    solution = nb.items[4]
    assert solution.text == "Worked: softmax(QK^T)" and solution.source == "tutor"
    teach = nb.items[1]
    assert teach.label == "Teach-back" and teach.source == "teach"
    assert teach.text == "r-teach" and teach.prompt == "p-teach"
    assert teach.score == pytest.approx(0.6) and teach.gaps == ["gap-teach"]
    assert nb.items[0].label == "Decay check" and nb.items[0].source == "retention"
    assert nb.items[3].source == "assess"


def test_an_empty_notebook_has_no_note_and_no_items(session):
    _, concept, _ = _seed(session)
    nb = build_notebook(session, concept)
    assert nb.note_body == "" and nb.note_updated_at is None and nb.items == []


def test_save_note_upserts_one_row_per_concept(session):
    _, concept, _ = _seed(session)
    first = save_note(session, concept.id, "draft")
    second = save_note(session, concept.id, "final")
    rows = session.exec(select(ConceptNote)).all()
    assert len(rows) == 1 and rows[0].body == "final"
    assert first.id == second.id and second.updated_at >= first.updated_at


def test_save_note_refuses_more_than_the_cap(session):
    _, concept, _ = _seed(session)
    save_note(session, concept.id, "x" * NOTE_MAX_CHARS)  # exactly the cap is fine
    with pytest.raises(NoteTooLong):
        save_note(session, concept.id, "x" * (NOTE_MAX_CHARS + 1))
    assert session.exec(select(ConceptNote)).one().body == "x" * NOTE_MAX_CHARS


def test_topic_notebook_lists_only_concepts_with_notes_or_work(session):
    topic, concept, other = _seed(session)
    third = Concept(track_id=concept.track_id, name="Blank note")
    session.add(third)
    session.commit()
    convo = _convo(session, topic, concept)
    _attempt(session, convo, "try", accepted=True, at=T0)
    session.add(ConceptNote(concept_id=other.id, body="note", updated_at=T0 + timedelta(days=1)))
    session.add(ConceptNote(concept_id=third.id, body="   ", updated_at=T0))  # blank: not listed
    session.add(Assessment(concept_id=third.id, kind="artifact_review", prompt="p"))  # not work
    session.commit()

    rows = topic_notebook(session, topic.id)

    assert [r.concept_id for r in rows] == [other.id, concept.id]  # latest activity first
    assert rows[0].has_note is True and rows[0].attempts == 0
    assert rows[1].has_note is False and rows[1].attempts == 1


# --- the managed section --------------------------------------------------------------------


def _nb(session, body="My notes here."):
    topic, concept, _ = _seed(session)
    convo = _convo(session, topic, concept)
    _attempt(session, convo, "line one\nline two", accepted=True, at=T0)
    _attempt(session, convo, "just a guess", accepted=False, at=T0 + timedelta(minutes=1))
    session.add(Assessment(concept_id=concept.id, kind="self_explanation", prompt="Explain it",
                           response="It weighs values by similarity.", score=0.62,
                           gaps=["no scaling", "no masking"], created_at=T0 + timedelta(hours=1)))
    session.add(Message(conversation_id=convo.id, role="tutor", content="Step 1\nStep 2",
                        reveals_solution=True, created_at=T0 + timedelta(minutes=5)))
    session.commit()
    save_note(session, concept.id, body)
    return topic, concept


def test_section_is_wrapped_in_markers_and_names_every_part(session):
    _, concept = _nb(session)
    section = render_notebook_section(build_notebook(session, concept), "medium",
                                      "Latest: **self_explanation**, score 0.62")

    lines = section.splitlines()
    assert lines[0].startswith(START_PREFIX + " sha=") and lines[-1] == END_MARKER
    for heading in ("## Notebook", "### My notes", "### My attempts", "### My explanations",
                    "### Worked solutions"):
        assert heading in lines
    assert "My notes here." in section
    assert "**Verdict:** medium" in section
    assert "Latest: **self_explanation**, score 0.62" in section
    assert "not inside it" in section
    assert "> line one\n> line two" in section
    assert "not accepted" in section
    assert "Self-explanation" in section and "score 0.62" in section
    assert "Gaps: no scaling; no masking" in section
    assert "> Step 1\n> Step 2" in section
    inner = "\n".join(lines[1:-1])  # the markers themselves are HTML comments ("<!--")
    assert "—" not in inner and "!" not in inner


def test_section_neutralizes_marker_text_in_learner_content(session):
    _, concept = _nb(session, body=f"sneaky\n{END_MARKER}\nmore\n{START_MARKER}")
    section = render_notebook_section(build_notebook(session, concept), "low")
    assert section.count(START_PREFIX) == 1 and section.count(END_MARKER) == 1
    # And a note carrying it splices cleanly on the next sync.
    once = splice_notebook_section("Mine.\n", section)
    assert splice_notebook_section(once, section) == once


def test_splice_appends_a_section_when_markers_are_missing():
    section = f"{START_MARKER}\nNEW\n{END_MARKER}"
    assert splice_notebook_section("# Title\n\nMine.\n", section) == (
        f"# Title\n\nMine.\n\n{section}\n")
    assert splice_notebook_section("no newline", section) == f"no newline\n\n{section}\n"
    assert splice_notebook_section("", section) == f"{section}\n"


def test_splice_replaces_only_between_the_markers():
    old = (f"---\ntitle: X\n---\nAbove, mine.\n{START_MARKER}\nOLD\nstuff\n{END_MARKER}\n"
           "Below, mine.\n")
    new = splice_notebook_section(old, f"{START_MARKER}\nNEW\n{END_MARKER}")
    assert new == (f"---\ntitle: X\n---\nAbove, mine.\n{START_MARKER}\nNEW\n{END_MARKER}\n"
                   "Below, mine.\n")


def test_splice_refuses_a_second_section_rather_than_delete_it():
    """A second complete section may be a copy the learner pasted (in a code block, say):
    removing it could delete their text, so the note is left alone and reported."""
    old = (f"A\n{START_MARKER}\none\n{END_MARKER}\nB\n```\n{START_MARKER}\ntwo\n"
           f"{END_MARKER}\n```\nC\n")
    with pytest.raises(MarkerError, match="more than one"):
        splice_notebook_section(old, f"{START_MARKER}\nNEW\n{END_MARKER}")


@pytest.mark.parametrize("text", [
    f"A\n{START_MARKER}\nno end\n",
    f"A\n{END_MARKER}\nno start\n",
    f"{END_MARKER}\n{START_MARKER}\n",
    f"{START_MARKER}\n{START_MARKER}\n{END_MARKER}\n",
])
def test_splice_refuses_unbalanced_markers(text):
    with pytest.raises(MarkerError):
        splice_notebook_section(text, f"{START_MARKER}\nNEW\n{END_MARKER}")


# --- writing the note -----------------------------------------------------------------------


def test_sync_creates_the_note_with_header_and_section(session, tmp_path):
    topic, concept = _nb(session)
    path = sync_concept(session, concept.id, str(tmp_path))

    assert path == _note_path(tmp_path)
    text = path.read_text()
    assert text.startswith("---\ntitle: Self-Attention\n")
    header, _, rest = text.partition(START_PREFIX)
    assert "concept_id: " in header and "verdict: untested" not in header
    assert "**Verdict:**" not in header and "Latest:" not in header  # both in the section
    assert "Part of [[build-llms]]." in header
    assert "**Verdict:**" in rest and "Latest: **self_explanation**, score 0.62" in rest
    assert text.count(START_PREFIX) == 1 and "My notes here." in text


def test_sync_preserves_what_the_learner_wrote_outside_the_markers(session, tmp_path):
    topic, concept = _nb(session)
    path = sync_concept(session, concept.id, str(tmp_path))
    edited = ("My own header line\n" + path.read_text()
              + "\n## Written in Obsidian\n\nKeep this exactly.  \n")
    path.write_text(edited)

    save_note(session, concept.id, "Updated in the app.")
    sync_concept(session, concept.id, str(tmp_path))

    text = path.read_text()
    before, _, rest = edited.partition(START_PREFIX)
    _, _, after = rest.partition(END_MARKER)
    assert text.startswith(before) and text.endswith(after)
    assert "Updated in the app." in text and "My notes here." not in text


def test_sync_appends_to_an_older_note_without_markers(session, tmp_path):
    topic, concept = _nb(session)
    path = _note_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("---\ntitle: Self-Attention\ntags: [adaptive-academy, concept]\nverdict: high\n"
                    "---\n# Self-Attention\n")
    sync_concept(session, concept.id, str(tmp_path))
    text = path.read_text()
    # Only the frontmatter verdict value changes outside the markers.
    assert text.startswith("---\ntitle: Self-Attention\ntags: [adaptive-academy, concept]\n"
                           "verdict: medium\n---\n# Self-Attention\n\n")
    assert text.rstrip().endswith(END_MARKER)


def test_sync_leaves_a_note_with_unbalanced_markers_untouched(session, tmp_path):
    topic, concept = _nb(session)
    path = _note_path(tmp_path)
    path.parent.mkdir(parents=True)
    broken = f"mine\n{START_MARKER}\nhalf a section\n"
    path.write_text(broken)
    with pytest.raises(MarkerError):
        sync_concept(session, concept.id, str(tmp_path))
    assert path.read_text() == broken


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_sync_refuses_a_note_that_is_a_symlink(session, tmp_path):
    topic, concept = _nb(session)
    outside = tmp_path / "outside.md"
    outside.write_text("not in the vault")
    vault = tmp_path / "vault"
    path = _note_path(vault)
    path.parent.mkdir(parents=True)
    path.symlink_to(outside)
    with pytest.raises(OSError):
        sync_concept(session, concept.id, str(vault))
    assert outside.read_text() == "not in the vault"


def test_sync_skips_the_demo_topic(session, tmp_path):
    topic, concept, _ = _seed(session, "Demo topic", demo=True)
    save_note(session, concept.id, "demo note")
    assert sync_concept(session, concept.id, str(tmp_path)) is None
    assert not (tmp_path / EXPORT_FOLDER).exists()


def test_export_keeps_learner_edits_and_adds_the_section(session, tmp_path):
    topic, concept = _nb(session)
    export_vault(session, topic.id, str(tmp_path))
    path = _note_path(tmp_path)
    assert START_PREFIX in path.read_text()
    path.write_text(path.read_text() + "\nMine, from Obsidian.\n")

    session.add(KnowledgeEstimate(concept_id=concept.id, level="low"))
    session.commit()
    res = export_vault(session, topic.id, str(tmp_path))

    text = path.read_text()
    assert text.endswith("\nMine, from Obsidian.\n")
    assert text.count(START_PREFIX) == 1
    assert "**Verdict:** low" in text and "\nverdict: low\n" in text
    assert str(path) in res.written


def test_export_reports_a_note_it_could_not_update_and_writes_the_rest(session, tmp_path):
    topic, concept = _nb(session)
    path = _note_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(f"{START_MARKER}\nbroken\n")

    res = export_vault(session, topic.id, str(tmp_path))

    assert path.read_text() == f"{START_MARKER}\nbroken\n"
    assert str(path) not in res.written
    assert any("self-attention.md" in p for p in res.problems)
    assert _note_path(tmp_path, concept_slug="softmax").exists()


# --- write triggers -------------------------------------------------------------------------


def test_no_vault_means_nothing_is_queued(session):
    NOTEBOOK_SYNC.reset()
    _, concept, _ = _seed(session)
    save_note(session, concept.id, "x")
    assert NOTEBOOK_SYNC.pending_count() == 0


def test_saving_a_note_rewrites_the_section(session, vault_sync):
    _, concept, _ = _seed(session)
    save_note(session, concept.id, "Saved from the app.")
    assert NOTEBOOK_SYNC.drain() == 1
    assert "Saved from the app." in _note_path(vault_sync).read_text()
    assert NOTEBOOK_SYNC.status()["last_synced_at"] is not None


def test_an_attempt_and_a_grade_each_rewrite_the_section(session, vault_sync):
    topic, concept, _ = _seed(session)
    convo = _convo(session, topic, concept)
    _attempt(session, convo, "my working", accepted=True, at=T0)
    NOTEBOOK_SYNC.drain()
    assert "my working" in _note_path(vault_sync).read_text()

    session.add(Assessment(concept_id=concept.id, kind="teach", prompt="p",
                           response="taught it", score=0.7))
    session.commit()
    NOTEBOOK_SYNC.drain()
    assert "taught it" in _note_path(vault_sync).read_text()


def test_a_revealed_solution_rewrites_the_section(session, vault_sync):
    topic, concept, _ = _seed(session)
    convo = _convo(session, topic, concept)
    session.add(Message(conversation_id=convo.id, role="tutor", content="the worked answer",
                        reveals_solution=True))
    session.commit()
    NOTEBOOK_SYNC.drain()
    assert "the worked answer" in _note_path(vault_sync).read_text()


def test_a_rolled_back_change_queues_nothing(session, vault_sync):
    _, concept, _ = _seed(session)
    NOTEBOOK_SYNC.drain()
    session.add(ConceptNote(concept_id=concept.id, body="never saved"))
    session.flush()
    session.rollback()
    assert NOTEBOOK_SYNC.pending_count() == 0


def test_a_vault_error_never_fails_the_action_and_shows_on_status(session, vault_sync):
    topic, concept, _ = _seed(session)
    path = _note_path(vault_sync)
    path.parent.mkdir(parents=True)
    path.write_text(f"{START_MARKER}\nunbalanced\n")

    save_note(session, concept.id, "still saved")  # the action itself succeeds
    NOTEBOOK_SYNC.drain()

    assert session.exec(select(ConceptNote)).one().body == "still saved"
    status = NOTEBOOK_SYNC.status()
    assert "self-attention.md" in status["last_error"]
    assert "markers" in status["last_error"]
    events = session.exec(select(AgentEvent).where(AgentEvent.kind == "vault:sync_failed")).all()
    assert len(events) == 1 and events[0].topic_id == topic.id


def test_a_vault_that_disappeared_is_reported_not_raised(session, vault_sync):
    _, concept, _ = _seed(session)
    shutil.rmtree(vault_sync)
    save_note(session, concept.id, "x")
    NOTEBOOK_SYNC.drain()
    assert "does not exist" in NOTEBOOK_SYNC.status()["last_error"]


def test_the_queue_is_bounded(session, vault_sync, monkeypatch):
    monkeypatch.setattr(NOTEBOOK_SYNC, "max_pending", 2)
    topic, concept, other = _seed(session)
    third = Concept(track_id=concept.track_id, name="Third")
    session.add(third)
    session.commit()
    for c in (concept, other, third):
        save_note(session, c.id, "n")
    assert NOTEBOOK_SYNC.pending_count() == 2
    assert NOTEBOOK_SYNC.status()["dropped"] == 1
    assert "queue" in NOTEBOOK_SYNC.status()["last_error"]


# --- the app's own notes are never re-ingested ---------------------------------------------


def test_ingest_and_reindex_skip_the_export_folder_even_as_the_subfolder(session, tmp_path):
    topic, concept = _nb(session)
    export_vault(session, topic.id, str(tmp_path))
    for sub in ("", EXPORT_FOLDER, f"{EXPORT_FOLDER}/build-llms"):
        res = ingest_vault(session, topic.id, str(tmp_path), subfolder=sub)
        assert res.count == 0, sub
        idx = reindex_vault(session, topic.id, str(tmp_path), subfolder=sub)
        assert idx.indexed == 0, sub
    assert session.exec(select(SourceDoc)).all() == []


def test_a_file_database_syncs_on_the_background_thread(tmp_path, vault_sync):
    """Off the request path: with a real (pooled) engine, the commit only queues the concept
    and the notebook-sync thread writes the note."""
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'live.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as s:
            _, concept, _ = _seed(s)
            save_note(s, concept.id, "written by the worker")
        assert NOTEBOOK_SYNC.flush(timeout=10)
        assert "written by the worker" in _note_path(vault_sync).read_text()
        assert NOTEBOOK_SYNC.status()["pending"] == 0
    finally:
        engine.dispose()


def test_a_deleted_grade_rewrites_the_section(session, vault_sync):
    _, concept, _ = _seed(session)
    graded = Assessment(concept_id=concept.id, kind="recall", prompt="p", response="old recall")
    session.add(graded)
    session.commit()
    NOTEBOOK_SYNC.drain()
    assert "old recall" in _note_path(vault_sync).read_text()
    session.delete(graded)
    session.commit()
    NOTEBOOK_SYNC.drain()
    assert "old recall" not in _note_path(vault_sync).read_text()


def test_a_note_too_large_or_not_utf8_is_left_alone(session, tmp_path, monkeypatch):
    from adaptive_academy.engine.notebook_sync import UnsafeNote

    topic, concept = _nb(session)
    path = _note_path(tmp_path)
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(notebook_sync, "NOTE_FILE_MAX_CHARS", 10)
    path.write_text("x" * 11)
    with pytest.raises(UnsafeNote):
        sync_concept(session, concept.id, str(tmp_path))
    assert path.read_text() == "x" * 11

    path.write_bytes(b"\xff\xfe not utf-8")
    monkeypatch.setattr(notebook_sync, "NOTE_FILE_MAX_CHARS", 1_000_000)
    with pytest.raises(UnsafeNote):
        sync_concept(session, concept.id, str(tmp_path))
    assert path.read_bytes() == b"\xff\xfe not utf-8"


def test_an_edit_made_during_a_sync_is_kept(session, tmp_path, monkeypatch):
    """Obsidian saves the note between our read and our write: the write is redone on the
    new text instead of overwriting the learner's edit."""
    topic, concept = _nb(session)
    path = sync_concept(session, concept.id, str(tmp_path))
    real_splice = notebook_sync.splice_notebook_section
    calls = []

    def splice_while_learner_types(text, section):
        calls.append(text)
        if len(calls) == 1:
            os.utime(path, ns=(1, 1))  # a different mtime: the note changed under us
            path.write_text(text + "Typed in Obsidian mid-sync.\n")
        return real_splice(text, section)

    monkeypatch.setattr(notebook_sync, "splice_notebook_section", splice_while_learner_types)
    save_note(session, concept.id, "Changed in the app.")
    sync_concept(session, concept.id, str(tmp_path))

    text = path.read_text()
    assert len(calls) == 2
    assert text.endswith("Typed in Obsidian mid-sync.\n") and "Changed in the app." in text


# --- review fixes ----------------------------------------------------------------------------


def test_a_rolled_back_savepoint_keeps_the_queued_keys(session, vault_sync):
    """memory.index_text embeds inside begin_nested(): a failed embed rolls back only that
    savepoint, and the reveal and the grade written in the same transaction still sync."""
    from adaptive_academy.models import Chunk

    topic, concept, _ = _seed(session)
    convo = _convo(session, topic, concept)
    NOTEBOOK_SYNC.drain()
    session.add(Message(conversation_id=convo.id, role="tutor", content="revealed answer",
                        reveals_solution=True))
    session.add(Assessment(concept_id=concept.id, kind="teach", prompt="p",
                           response="graded words", score=0.5))
    session.flush()
    with pytest.raises(RuntimeError):
        with session.begin_nested():
            session.add(Chunk(kind="message", source_ref="x", text="t", content_hash="h"))
            session.flush()
            raise RuntimeError("embedder failed")
    session.commit()
    NOTEBOOK_SYNC.drain()
    text = _note_path(vault_sync).read_text()
    assert "revealed answer" in text and "graded words" in text


def test_a_row_moved_to_another_concept_rewrites_both(session, vault_sync):
    _, concept, other = _seed(session)
    graded = Assessment(concept_id=concept.id, kind="recall", prompt="p", response="moved text")
    session.add(graded)
    session.commit()
    NOTEBOOK_SYNC.drain()
    graded.concept_id = other.id
    session.add(graded)
    session.commit()
    assert NOTEBOOK_SYNC.drain() == 2
    assert "moved text" not in _note_path(vault_sync).read_text()
    assert "moved text" in _note_path(vault_sync, concept_slug="softmax").read_text()


def test_a_legacy_note_gets_its_frontmatter_verdict_kept_current(session, tmp_path):
    """Notes exported before the notebook: the frontmatter verdict value follows the grade;
    the old **Verdict:** body line is outside the markers and stays as it was."""
    topic, concept = _nb(session)
    path = _note_path(tmp_path)
    path.parent.mkdir(parents=True)
    legacy = ("---\ntitle: Self-Attention\ntags: [adaptive-academy, concept]\nverdict: untested\n"
              "load_bearing: true\n---\n\n# Self-Attention\n\n**Verdict:** untested\n\n"
              "No assessments yet.\n\nPart of [[build-llms]].\n")
    path.write_text(legacy)
    sync_concept(session, concept.id, str(tmp_path))
    text = path.read_text()
    assert text.startswith(legacy.replace("verdict: untested", "verdict: medium"))
    assert "**Verdict:** untested" in text  # the legacy body line is the learner's now
    assert "**Verdict:** medium" in text.partition(START_PREFIX)[2]


def test_set_frontmatter_value_touches_only_that_key():
    from adaptive_academy.engine.notebook import set_frontmatter_value

    text = "---\r\ntitle: X\r\nverdict: low\r\nverdicts: keep\r\n---\r\nverdict: body\r\n"
    assert set_frontmatter_value(text, "verdict", "high") == text.replace(
        "verdict: low", "verdict: high")
    assert set_frontmatter_value("no frontmatter\nverdict: x\n", "verdict", "y") == (
        "no frontmatter\nverdict: x\n")
    assert set_frontmatter_value("---\ntitle: X\n---\nverdict: x\n", "verdict", "y") == (
        "---\ntitle: X\n---\nverdict: x\n")


def test_edits_inside_the_section_are_not_overwritten(session, vault_sync):
    _, concept = _nb(session)
    path = sync_concept(session, concept.id, str(vault_sync))
    edited = path.read_text().replace("My notes here.", "I typed this inside the section.")
    path.write_text(edited)

    save_note(session, concept.id, "New from the app.")
    with pytest.raises(SectionEdited):
        sync_concept(session, concept.id, str(vault_sync))
    assert path.read_text() == edited

    NOTEBOOK_SYNC.drain()
    assert "edited in Obsidian" in NOTEBOOK_SYNC.status()["last_error"]
    # Deleting the section (markers too) lets the next sync write a fresh one.
    head, _, rest = edited.partition(START_PREFIX)
    path.write_text(head + rest.partition(END_MARKER)[2])
    sync_concept(session, concept.id, str(vault_sync))
    assert "New from the app." in path.read_text()


def test_crlf_notes_keep_their_line_endings(session, tmp_path):
    _, concept = _nb(session)
    path = _note_path(tmp_path)
    path.parent.mkdir(parents=True)
    original = (b"---\r\ntitle: Self-Attention\r\ntags: [adaptive-academy, concept]\r\n"
                b"verdict: low\r\n---\r\n# Mine\r\nKeep.\r\n")
    path.write_bytes(original)
    sync_concept(session, concept.id, str(tmp_path))
    raw = path.read_bytes()
    assert raw.startswith(original.replace(b"verdict: low", b"verdict: medium"))
    assert b"\n" not in raw.replace(b"\r\n", b"")  # every line ends in CRLF
    # A second sync finds its own section (the hash ignores line endings) and changes nothing.
    sync_concept(session, concept.id, str(tmp_path))
    assert path.read_bytes() == raw


# --- names that collide ----------------------------------------------------------------------


def _topic_with(session, title, names):
    topic = Topic(title=title)
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.commit()
    concepts = []
    for name in names:
        c = Concept(track_id=track.id, name=name)
        session.add(c)
        session.commit()
        concepts.append(c)
    return topic, concepts


def test_slugify_keeps_letters_in_any_script():
    from adaptive_academy.engine.vault import slugify

    assert slugify("微积分") == "微积分"
    assert slugify("Café Théorie") == "café-théorie"
    assert slugify("snake_case & C++") == "snake-case-c"
    assert slugify("++") == ""


def test_names_that_slug_alike_never_share_a_note(session, tmp_path):
    topic, (cpp, csharp, calc, symbols) = _topic_with(
        session, "Languages", ["C++", "C#", "微积分", "++"])
    for c in (cpp, csharp, calc, symbols):
        save_note(session, c.id, f"note for {c.name}")
    res = export_vault(session, topic.id, str(tmp_path))

    concepts_dir = tmp_path / EXPORT_FOLDER / "languages" / "Concepts"
    assert (concepts_dir / "c.md").read_text().count("note for C++") == 1
    assert "note for C#" in (concepts_dir / f"c-{csharp.id}.md").read_text()
    assert "note for 微积分" in (concepts_dir / "微积分.md").read_text()
    assert "note for ++" in (concepts_dir / f"concept-{symbols.id}.md").read_text()
    assert len(res.written) == 5  # the hub and four distinct notes
    hub = (tmp_path / EXPORT_FOLDER / "languages" / "languages.md").read_text()
    assert f"[[c-{csharp.id}|C#]]" in hub and "[[c|C++]]" in hub
    # A sync of one concept finds the same file.
    assert sync_concept(session, csharp.id, str(tmp_path)) == concepts_dir / f"c-{csharp.id}.md"


def test_a_file_that_is_another_notes_is_never_overwritten(session, tmp_path):
    topic, (concept,) = _topic_with(session, "Languages", ["Rust"])
    concepts_dir = tmp_path / EXPORT_FOLDER / "languages" / "Concepts"
    concepts_dir.mkdir(parents=True)
    theirs = "---\ntitle: RUST (the game)\n---\nnot this concept\n"
    (concepts_dir / "rust.md").write_text(theirs)

    path = sync_concept(session, concept.id, str(tmp_path))

    assert (concepts_dir / "rust.md").read_text() == theirs
    assert path == concepts_dir / f"rust-{concept.id}.md"


def test_topics_that_slug_alike_get_their_own_folders(session, tmp_path):
    first, (a,) = _topic_with(session, "Linear Algebra", ["Vectors"])
    second, (b,) = _topic_with(session, "linear algebra", ["Vectors"])
    save_note(session, a.id, "first topic")
    save_note(session, b.id, "second topic")

    path_a = sync_concept(session, a.id, str(tmp_path))
    path_b = sync_concept(session, b.id, str(tmp_path))

    assert path_a.parent.parent.name == "linear-algebra"
    assert path_b.parent.parent.name == f"linear-algebra-{second.id}"
    assert "first topic" in path_a.read_text() and "second topic" in path_b.read_text()
    hub_b = path_b.parent.parent / f"linear-algebra-{second.id}.md"
    assert f"topic_id: {second.id}" in hub_b.read_text()
    assert f"Part of [[linear-algebra-{second.id}]]." in path_b.read_text()


def test_a_folder_whose_hub_is_another_topics_is_not_used(session, tmp_path):
    topic, (concept,) = _topic_with(session, "Graphs", ["Trees"])
    folder = tmp_path / EXPORT_FOLDER / "graphs"
    folder.mkdir(parents=True)
    (folder / "graphs.md").write_text("---\ntitle: Graphs\ntopic_id: 999\n---\n")
    path = sync_concept(session, concept.id, str(tmp_path))
    assert path.parent.parent.name == f"graphs-{topic.id}"
    assert (folder / "graphs.md").read_text() == "---\ntitle: Graphs\ntopic_id: 999\n---\n"


def test_registering_a_vault_needs_an_obsidian_folder(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    NOTEBOOK_SYNC.reset()
    try:
        with pytest.raises(ValueError, match="no .obsidian folder"):
            notebook_sync.register_vault_path(str(plain))
        assert notebook_sync.sync_vault_path() == ""
        (plain / ".obsidian").mkdir()
        assert notebook_sync.register_vault_path(str(plain)) == str(plain.resolve())
    finally:
        NOTEBOOK_SYNC.reset()


def test_the_env_vault_is_trusted_without_an_obsidian_folder(session, tmp_path, monkeypatch):
    from adaptive_academy.settings import settings

    NOTEBOOK_SYNC.reset()
    monkeypatch.setattr(settings, "obsidian_vault_path", str(tmp_path))
    try:
        _, concept, _ = _seed(session)
        save_note(session, concept.id, "env vault")
        NOTEBOOK_SYNC.drain()
        assert "env vault" in _note_path(tmp_path).read_text()
    finally:
        NOTEBOOK_SYNC.reset()


def test_the_queue_keeps_the_same_row_from_two_databases_apart(vault_sync):
    from sqlmodel import create_engine

    one, two = create_engine("sqlite://"), create_engine("sqlite://")
    NOTEBOOK_SYNC.request(one, {("concept", 1)})
    NOTEBOOK_SYNC.request(two, {("concept", 1)})
    NOTEBOOK_SYNC.request(one, {("concept", 1)})
    assert NOTEBOOK_SYNC.pending_count() == 2


# --- second review round ---------------------------------------------------------------------


def test_a_released_savepoint_does_not_queue_before_the_outer_commit(session, vault_sync):
    """after_commit also fires when a SAVEPOINT is released (memory.index_* use
    begin_nested): a writer woken then would render before the outer commit and miss the
    new row. The keys wait for the outermost commit."""
    from adaptive_academy.models import Chunk

    _, concept, _ = _seed(session)
    NOTEBOOK_SYNC.drain()
    session.add(Assessment(concept_id=concept.id, kind="teach", prompt="p",
                           response="the teach-back", score=0.6))
    session.flush()
    with session.begin_nested():
        session.add(Chunk(kind="assessment", source_ref="a:1", text="t", content_hash="h"))
    assert NOTEBOOK_SYNC.pending_count() == 0  # nothing woken while the transaction is open
    assert NOTEBOOK_SYNC.drain() == 0
    session.commit()
    assert NOTEBOOK_SYNC.pending_count() == 1
    NOTEBOOK_SYNC.drain()
    assert "the teach-back" in _note_path(vault_sync).read_text()


def test_the_section_has_no_trailing_spaces(session):
    _, concept = _nb(session, body="hard break  \nnext line")
    section = render_notebook_section(build_notebook(session, concept), "medium",
                                      "Latest: **teach**, score 0.62  \nRight idea.  \nGaps: x")
    assert all(line == line.rstrip() for line in section.splitlines())
    assert "Latest: **teach**, score 0.62\n\nRight idea.\n\nGaps: x" in section


@pytest.mark.parametrize("tidy", [
    lambda body: "\n".join(line.rstrip() for line in body.split("\n")),  # trim on save
    lambda body: body.replace("### My notes\n", "### My notes\n\n", 1),  # an added blank line
    lambda body: body.replace("\n", "\r\n"),  # line endings changed
    lambda body: body + "\n\n",  # blank lines at the end
])
def test_whitespace_tidying_inside_the_section_is_not_an_edit(session, tmp_path, tidy):
    _, concept = _nb(session)
    path = sync_concept(session, concept.id, str(tmp_path))
    text = path.read_text()
    head, start, rest = text.partition(START_PREFIX)
    marker_rest, _, after_start = rest.partition("\n")
    body, end, tail = after_start.partition(END_MARKER)
    path.write_text(head + start + marker_rest + "\n" + tidy(body) + end + tail)

    save_note(session, concept.id, "Still syncs.")
    sync_concept(session, concept.id, str(tmp_path))
    assert "Still syncs." in path.read_text()


def test_a_real_edit_is_still_caught_after_tidying_rules(session, tmp_path):
    _, concept = _nb(session)
    path = sync_concept(session, concept.id, str(tmp_path))
    path.write_text(path.read_text().replace("> Step 1", "> Step 1, my own fix  "))
    with pytest.raises(SectionEdited):
        sync_concept(session, concept.id, str(tmp_path))


def test_a_section_hashed_the_first_way_still_syncs(session, tmp_path):
    from adaptive_academy.engine.notebook import _legacy_digest

    _, concept = _nb(session)
    path = sync_concept(session, concept.id, str(tmp_path))
    text = path.read_text()
    head, _, rest = text.partition(START_PREFIX)
    marker_rest, _, after_start = rest.partition("\n")
    body, end, tail = after_start.partition(END_MARKER)
    path.write_text(head + f"{START_PREFIX} sha={_legacy_digest(body)} -->\n" + body + end + tail)
    save_note(session, concept.id, "Rehashed.")
    sync_concept(session, concept.id, str(tmp_path))
    assert "Rehashed." in path.read_text()


def test_problems_name_the_note_that_was_checked(session, vault_sync):
    topic, (cpp, csharp) = _topic_with(session, "Languages", ["C++", "C#"])
    export_vault(session, topic.id, str(vault_sync))
    path = vault_sync / EXPORT_FOLDER / "languages" / "Concepts" / f"c-{csharp.id}.md"
    path.write_text(path.read_text().replace("Nothing yet.", "typed inside", 1))
    save_note(session, csharp.id, "x")
    NOTEBOOK_SYNC.drain()
    assert f"c-{csharp.id}.md" in NOTEBOOK_SYNC.status()["last_error"]


def test_an_older_ascii_named_note_is_reused_not_copied(session, tmp_path):
    topic, (calc,) = _topic_with(session, "Maths", ["Cálculo"])
    concepts_dir = tmp_path / EXPORT_FOLDER / "maths" / "Concepts"
    concepts_dir.mkdir(parents=True)
    (tmp_path / EXPORT_FOLDER / "maths" / "maths.md").write_text("---\ntitle: Maths\n---\n")
    old = concepts_dir / "c-lculo.md"
    old.write_text("---\ntitle: Cálculo\ntags: [adaptive-academy, concept]\nverdict: untested\n"
                   "---\nMine.\n")
    path = sync_concept(session, calc.id, str(tmp_path))
    assert path == old and not (concepts_dir / "cálculo.md").exists()
    assert path.read_text().startswith("---\ntitle: Cálculo\n")


def test_an_older_ascii_named_topic_folder_is_reused(session, tmp_path):
    topic, (concept,) = _topic_with(session, "Straße", ["Kurven"])
    old = tmp_path / EXPORT_FOLDER / "stra-e"
    old.mkdir(parents=True)
    (old / "stra-e.md").write_text("---\ntitle: Straße\ntags: [adaptive-academy]\n---\n")
    path = sync_concept(session, concept.id, str(tmp_path))
    assert path.parent.parent == old
    assert not (tmp_path / EXPORT_FOLDER / "strasse").exists()


def test_a_quoted_title_from_obsidian_still_matches(session, tmp_path):
    topic, (concept,) = _topic_with(session, "Linear Algebra: Foundations", ["Rank"])
    folder = tmp_path / EXPORT_FOLDER / "linear-algebra-foundations"
    folder.mkdir(parents=True)
    hub = folder / "linear-algebra-foundations.md"
    hub.write_text('---\ntitle: "Linear Algebra: Foundations"\ntags: [adaptive-academy]\n---\n')
    path = sync_concept(session, concept.id, str(tmp_path))
    assert path.parent.parent == folder


def test_export_all_reports_a_topic_it_could_not_write_and_does_the_rest(session, tmp_path):
    from adaptive_academy.engine.vault import export_all_topics

    blocked, _ = _topic_with(session, "Blocked", ["A"])
    fine, _ = _topic_with(session, "Fine", ["B"])
    folder = tmp_path / EXPORT_FOLDER / "blocked"
    folder.mkdir(parents=True)
    (folder / "blocked.md").write_text("---\ntitle: Blocked\ntopic_id: 999\n---\n")
    (folder.parent / f"blocked-{blocked.id}").mkdir()
    (folder.parent / f"blocked-{blocked.id}" / f"blocked-{blocked.id}.md").write_text(
        "---\ntitle: Someone else\ntopic_id: 998\n---\n")
    res = export_all_topics(session, str(tmp_path))
    assert res.topics == 2
    assert any(p.startswith("Blocked:") for p in res.problems)
    assert (tmp_path / EXPORT_FOLDER / "fine" / "fine.md").exists()


@pytest.mark.parametrize("text", [
    "---\ntitle: X\nverdict: low\nno closing line\n",  # unclosed block
    "---\nnotes: \"a long value\nverdict: low\"\n---\nbody\n",  # inside a quoted value
    "verdict: low\n",  # no frontmatter at all
])
def test_frontmatter_edits_stay_inside_a_closed_block(text):
    from adaptive_academy.engine.notebook import set_frontmatter_value

    assert set_frontmatter_value(text, "verdict", "high") == text


def test_a_closing_line_with_trailing_spaces_still_closes_the_block():
    from adaptive_academy.engine.notebook import set_frontmatter_value

    text = "---\nverdict: low\n---   \nverdict: body\n"
    assert set_frontmatter_value(text, "verdict", "high") == (
        "---\nverdict: high\n---   \nverdict: body\n")


def test_a_learners_own_verdict_key_is_never_changed(session, tmp_path):
    """A note with no title or id of ours at our path is spliced, but its frontmatter is not
    the app's: a `verdict:` there is the learner's."""
    _, concept = _nb(session)
    path = _note_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("---\nverdict: my own call\n---\nMine.\n")
    sync_concept(session, concept.id, str(tmp_path))
    text = path.read_text()
    assert text.startswith("---\nverdict: my own call\n---\nMine.\n")
    assert START_PREFIX in text


def test_ownership_is_checked_again_when_writing(session, tmp_path):
    from adaptive_academy.engine.notebook_sync import UnsafeNote, write_note_file

    _, concept = _nb(session)
    path = _note_path(tmp_path)
    path.parent.mkdir(parents=True)
    theirs = "---\ntitle: Other\nconcept_id: 999\n---\nNot ours.\n"
    path.write_text(theirs)
    with pytest.raises(UnsafeNote):
        write_note_file(tmp_path.resolve(), path.resolve(), "header", f"{START_MARKER}\nx\n{END_MARKER}",
                        "low", concept=concept)
    assert path.read_text() == theirs


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_a_linked_obsidian_folder_counts(tmp_path):
    real = tmp_path / "config"
    real.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".obsidian").symlink_to(real, target_is_directory=True)
    NOTEBOOK_SYNC.reset()
    try:
        assert notebook_sync.register_vault_path(str(vault)) == str(vault.resolve())
    finally:
        NOTEBOOK_SYNC.reset()


# --- third review round ----------------------------------------------------------------------


def test_two_same_named_concepts_never_share_an_older_note(session, tmp_path):
    """A legacy limits.md (title only) is the first "Limits" concept's; the second one gets
    its own id-suffixed note and never takes or swaps that one."""
    topic, (first, second) = _topic_with(session, "Analysis", ["Limits", "Limits"])
    concepts_dir = tmp_path / EXPORT_FOLDER / "analysis" / "Concepts"
    concepts_dir.mkdir(parents=True)
    (tmp_path / EXPORT_FOLDER / "analysis" / "analysis.md").write_text("---\ntitle: Analysis\n---\n")
    legacy = concepts_dir / "limits.md"
    legacy.write_text("---\ntitle: Limits\ntags: [adaptive-academy, concept]\n---\nMine.\n")
    save_note(session, first.id, "first concept")
    save_note(session, second.id, "second concept")

    for _ in range(2):  # every sync, not just the first
        assert sync_concept(session, first.id, str(tmp_path)) == legacy
        assert sync_concept(session, second.id, str(tmp_path)) == (
            concepts_dir / f"limits-{second.id}.md")
    assert "first concept" in legacy.read_text() and "second concept" not in legacy.read_text()
    assert "second concept" in (concepts_dir / f"limits-{second.id}.md").read_text()
    res = export_vault(session, topic.id, str(tmp_path))
    assert str(legacy) in res.written and "second concept" not in legacy.read_text()


def test_two_same_named_topics_never_share_an_older_folder(session, tmp_path):
    first, (a,) = _topic_with(session, "Calculus", ["Derivatives"])
    second, (b,) = _topic_with(session, "Calculus", ["Integrals"])
    old = tmp_path / EXPORT_FOLDER / "calculus"
    old.mkdir(parents=True)
    hub = old / "calculus.md"
    hub.write_text("---\ntitle: Calculus\ntags: [adaptive-academy]\n---\n")
    save_note(session, b.id, "second topic")
    path_b = sync_concept(session, b.id, str(tmp_path))
    assert path_b.parent.parent.name == f"calculus-{second.id}"
    assert not (old / "Concepts").exists()  # nothing of topic 2's in topic 1's folder
    path_a = sync_concept(session, a.id, str(tmp_path))
    assert path_a.parent.parent == old


def test_an_older_note_under_another_name_is_taken_on_an_id_match(session, tmp_path):
    topic, (calc, other) = _topic_with(session, "Maths", ["Cálculo", "Cálculo"])
    concepts_dir = tmp_path / EXPORT_FOLDER / "maths" / "Concepts"
    concepts_dir.mkdir(parents=True)
    (tmp_path / EXPORT_FOLDER / "maths" / "maths.md").write_text("---\ntitle: Maths\n---\n")
    # The second Cálculo's own note under the old name (it carries its id).
    old = concepts_dir / "c-lculo.md"
    old.write_text(f"---\ntitle: Cálculo\nconcept_id: {other.id}\n---\n")
    assert sync_concept(session, other.id, str(tmp_path)) == old
    assert sync_concept(session, calc.id, str(tmp_path)) == concepts_dir / "cálculo.md"


def test_an_escaped_backslash_does_not_hide_later_keys():
    from adaptive_academy.engine.notebook import frontmatter_values, set_frontmatter_value

    text = '---\naliases: "C:\\\\"\nconcept_id: 7\nverdict: low\n---\n'
    assert frontmatter_values(text)["concept_id"] == "7"
    assert "verdict: high" in set_frontmatter_value(text, "verdict", "high")
    # An escaped quote still keeps the value open onto the next line.
    open_value = '---\nnote: "a \\" b\nverdict: inside\n"\nverdict: low\n---\n'
    assert set_frontmatter_value(open_value, "verdict", "high").endswith(
        'verdict: inside\n"\nverdict: high\n---\n')


def test_block_list_tags_count_as_ours(session, tmp_path):
    _, concept = _nb(session)
    path = _note_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("---\ntitle: Self-Attention\ntags:\n  - adaptive-academy\n  - concept\n"
                    "verdict: untested\n---\n")
    sync_concept(session, concept.id, str(tmp_path))
    assert "\nverdict: medium\n" in path.read_text()


def test_save_note_with_a_base_saves_only_over_that_version(session):
    from adaptive_academy.engine.notebook import NoteConflict

    _, concept, _ = _seed(session)
    first_at = save_note(session, concept.id, "one", base_updated_at=None).updated_at
    with pytest.raises(NoteConflict) as created:
        save_note(session, concept.id, "two", base_updated_at=None)  # one exists now
    assert created.value.note.body == "one"
    second = save_note(session, concept.id, "two", base_updated_at=first_at)
    assert second.body == "two" and second.updated_at != first_at
    with pytest.raises(NoteConflict) as stale:
        save_note(session, concept.id, "three", base_updated_at=first_at)
    assert stale.value.note.body == "two"
    assert session.exec(select(ConceptNote)).one().body == "two"


def test_a_conditional_save_still_reaches_the_vault(session, vault_sync):
    _, concept, _ = _seed(session)
    first_at = save_note(session, concept.id, "first", base_updated_at=None).updated_at
    NOTEBOOK_SYNC.drain()
    save_note(session, concept.id, "second", base_updated_at=first_at)
    assert NOTEBOOK_SYNC.drain() == 1
    assert "second" in _note_path(vault_sync).read_text()
