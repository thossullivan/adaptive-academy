import pytest
import os
import time

from sqlmodel import select

from adaptive_academy.engine.vault import (
    EXPORT_FOLDER,
    build_title_index,
    ingest_vault,
    reindex_vault,
)
from adaptive_academy.models import AgentEvent, Chunk, SourceDoc, Topic, VaultLink


def _topic(session) -> Topic:
    topic = Topic(title="Memory retrieval")
    session.add(topic)
    session.commit()
    session.refresh(topic)
    return topic


def _write_linked_vault(root) -> None:
    (root / "alpha.md").write_text(
        "---\ntitle: Alpha\ntags: [memory, retrieval]\n---\n"
        "# Alpha\n\nAlpha explains [[Beta]] and [[Missing]].",
        encoding="utf-8",
    )
    (root / "beta.md").write_text(
        "---\ntitle: Beta\naliases: [Second]\n---\n"
        "# Beta\n\nBeta refers to [[Alpha]].",
        encoding="utf-8",
    )
    (root / "gamma.md").write_text(
        "# Gamma\n\nGamma resolves [[Second]] through an alias.",
        encoding="utf-8",
    )


def test_reindex_vault_is_incremental_and_rebuilds_links(session, tmp_path):
    topic = _topic(session)
    _write_linked_vault(tmp_path)
    export = tmp_path / EXPORT_FOLDER
    export.mkdir()
    (export / "generated.md").write_text("# Generated\n\nDo not index this.")

    title_index = build_title_index(tmp_path)
    assert title_index["alpha"] == (tmp_path / "alpha.md").resolve().as_uri()
    assert title_index["second"] == (tmp_path / "beta.md").resolve().as_uri()

    first = reindex_vault(session, topic.id, str(tmp_path))
    chunks = session.exec(select(Chunk).order_by(Chunk.source_ref, Chunk.ordinal)).all()
    links = session.exec(select(VaultLink).order_by(VaultLink.src_ref, VaultLink.id)).all()

    assert first.indexed == len(chunks) == 3
    assert first.skipped == first.removed == 0
    assert {chunk.source_ref for chunk in chunks} == {
        (tmp_path / name).resolve().as_uri()
        for name in ("alpha.md", "beta.md", "gamma.md")
    }
    alpha_chunk = next(chunk for chunk in chunks if chunk.source_ref.endswith("alpha.md"))
    assert alpha_chunk.meta == {"tags": ["memory", "retrieval"], "aliases": []}
    assert any(link.dst_title == "Beta" and link.dst_ref.endswith("beta.md") for link in links)
    assert any(link.dst_title == "Second" and link.dst_ref.endswith("beta.md") for link in links)
    assert any(link.dst_title == "Missing" and link.dst_ref == "" for link in links)

    unchanged_link_ids = {
        link.src_ref: link.id for link in links if not link.src_ref.endswith("alpha.md")
    }
    second = reindex_vault(session, topic.id, str(tmp_path))
    assert second.indexed == second.removed == 0
    assert second.skipped == 3

    alpha_path = tmp_path / "alpha.md"
    prior_mtime = alpha_path.stat().st_mtime
    alpha_path.write_text(
        "---\ntitle: Alpha\ntags: [memory, edited]\n---\n"
        "# Alpha\n\nAlpha now links only to [[Gamma]].",
        encoding="utf-8",
    )
    os.utime(alpha_path, (prior_mtime + 1, prior_mtime + 1))
    edited = reindex_vault(session, topic.id, str(tmp_path))
    assert edited.indexed == 1
    assert edited.skipped == 2
    current_links = session.exec(select(VaultLink).order_by(VaultLink.src_ref, VaultLink.id)).all()
    assert any(link.src_ref.endswith("alpha.md") and link.dst_ref.endswith("gamma.md")
               for link in current_links)
    assert {
        link.src_ref: link.id
        for link in current_links
        if not link.src_ref.endswith("alpha.md")
    } == unchanged_link_ids

    (tmp_path / "gamma.md").unlink()
    deleted = reindex_vault(session, topic.id, str(tmp_path))
    assert deleted.removed == 1
    assert not session.exec(
        select(Chunk).where(Chunk.source_ref.endswith("gamma.md"))
    ).all()
    assert not session.exec(
        select(VaultLink).where(VaultLink.src_ref.endswith("gamma.md"))
    ).all()


def test_reindex_vault_skips_non_utf8_and_emits_event(session, tmp_path):
    topic = _topic(session)
    (tmp_path / "valid.md").write_text("# Valid\n\nReadable text.", encoding="utf-8")
    (tmp_path / "invalid.md").write_bytes(b"\xff\xfe\x00")

    result = reindex_vault(session, topic.id, str(tmp_path))

    assert result.indexed == 1
    assert result.skipped == 1
    assert session.exec(select(Chunk)).one().source_ref.endswith("valid.md")
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:reindex")
    ).one()
    assert "skipped=1" in event.detail
    skipped_events = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:reindex_skipped")
    ).all()
    assert len(skipped_events) == 1
    assert skipped_events[0].detail.endswith("invalid.md UnicodeDecodeError")


def test_reindex_vault_skips_outside_file_symlink_and_indexes_normal_note(
    session,
    tmp_path,
):
    topic = _topic(session)
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Secret\n\nOutside vault text.", encoding="utf-8")
    leaked = vault / "leaked.md"
    leaked.symlink_to(outside)
    normal = vault / "normal.md"
    normal.write_text("# Normal\n\nInside vault text.", encoding="utf-8")

    result = reindex_vault(session, topic.id, str(vault))

    chunks = session.exec(select(Chunk).where(Chunk.kind == "vault_note")).all()
    assert result.indexed == 1
    assert result.skipped == 1
    assert [chunk.source_ref for chunk in chunks] == [normal.resolve().as_uri()]
    skipped_events = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:reindex_skipped")
    ).all()
    assert len(skipped_events) == 1
    assert skipped_events[0].detail == (
        f"{leaked.absolute().as_uri()} outside-vault-or-symlink"
    )


def test_reindex_vault_indexes_normal_nested_note(session, tmp_path):
    topic = _topic(session)
    vault = tmp_path / "vault"
    nested = vault / "sub"
    nested.mkdir(parents=True)
    note = nested / "note.md"
    note.write_text("# Nested\n\nNormal nested text.", encoding="utf-8")

    result = reindex_vault(session, topic.id, str(vault))

    assert result.indexed == 1
    assert session.exec(select(Chunk)).one().source_ref == note.resolve().as_uri()


def test_reindex_vault_refuses_parent_symlink_swap(session, tmp_path, monkeypatch):
    topic = _topic(session)
    vault = tmp_path / "vault"
    nested = vault / "sub"
    nested.mkdir(parents=True)
    note = nested / "note.md"
    note.write_text("# Inside\n\nInside vault text.", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note.md").write_text(
        "# Secret\n\nOutside vault text.",
        encoding="utf-8",
    )
    original_open = os.open
    root_opens = 0
    file_opens = 0
    swapped = False

    def swap_parent() -> None:
        nonlocal swapped
        if swapped:
            return
        note.unlink()
        nested.rmdir()
        nested.symlink_to(outside, target_is_directory=True)
        swapped = True

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal root_opens, file_opens
        target = os.fspath(path)
        if dir_fd is None and target == os.fspath(vault):
            root_opens += 1
            if root_opens == 2:
                swap_parent()
        if dir_fd is None and target == os.fspath(note):
            file_opens += 1
            if file_opens == 2:
                swap_parent()
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", racing_open)

    result = reindex_vault(session, topic.id, str(vault))

    assert swapped
    assert result.indexed == 0
    assert result.skipped == 1
    assert not session.exec(select(Chunk)).all()
    skipped = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:reindex_skipped")
    ).one()
    assert skipped.detail.endswith("note.md outside-vault-or-symlink")


def test_ingest_vault_does_not_follow_symlinked_directory(session, tmp_path):
    topic = _topic(session)
    vault = tmp_path / "vault"
    vault.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "secret.md").write_text(
        "# Secret\n\nOutside directory text.",
        encoding="utf-8",
    )
    linked_dir = vault / "linked"
    linked_dir.symlink_to(outside_dir, target_is_directory=True)
    normal = vault / "normal.md"
    normal.write_text("# Normal\n\nInside vault text.", encoding="utf-8")

    result = ingest_vault(session, topic.id, str(vault))

    assert result.count == 1
    assert [doc.url for doc in session.exec(select(SourceDoc)).all()] == [
        normal.resolve().as_uri()
    ]
    assert [chunk.source_ref for chunk in session.exec(select(Chunk)).all()] == [
        normal.resolve().as_uri()
    ]
    skipped_events = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:reindex_skipped")
    ).all()
    assert len(skipped_events) == 1
    assert skipped_events[0].detail == (
        f"{linked_dir.absolute().as_uri()} outside-vault-or-symlink"
    )


def test_ingest_vault_registers_and_indexes_source_docs(session, tmp_path):
    topic = _topic(session)
    note = tmp_path / "note.md"
    note.write_text("# Indexed Note\n\nFull searchable content.", encoding="utf-8")

    result = ingest_vault(session, topic.id, str(tmp_path))

    assert result.count == 1
    assert session.exec(select(SourceDoc)).one().url == note.resolve().as_uri()
    chunk = session.exec(select(Chunk).where(Chunk.kind == "vault_note")).one()
    assert chunk.source_ref == note.resolve().as_uri()
    assert chunk.text == "Full searchable content."


def test_unchanged_reindex_of_200_notes_is_fast(session, tmp_path):
    topic = _topic(session)
    for index in range(200):
        (tmp_path / f"note-{index}.md").write_text(
            f"# Note {index}\n\nStable text {index}.", encoding="utf-8"
        )
    first = reindex_vault(session, topic.id, str(tmp_path))
    assert first.indexed == 200

    started = time.perf_counter()
    second = reindex_vault(session, topic.id, str(tmp_path))
    elapsed = time.perf_counter() - started

    assert second.indexed == 0
    assert second.skipped == 200
    assert elapsed < 2


def test_explicit_topic_reindex_preserves_note_owned_by_another_topic(
    session,
    tmp_path,
):
    first_topic = _topic(session)
    second_topic = Topic(title="Second owner")
    session.add(second_topic)
    session.commit()
    session.refresh(second_topic)
    note = tmp_path / "owned.md"
    note.write_text("# Owned\n\nKeep the first owner.", encoding="utf-8")
    seeded = reindex_vault(session, first_topic.id, str(tmp_path))
    assert seeded.indexed == 1

    result = reindex_vault(session, second_topic.id, str(tmp_path))

    chunk = session.exec(
        select(Chunk).where(Chunk.source_ref == note.resolve().as_uri())
    ).one()
    assert result.indexed == 0
    assert result.skipped == 1
    assert chunk.topic_id == first_topic.id
    event = session.exec(
        select(AgentEvent).where(
            AgentEvent.kind == "memory:reindex_owned_elsewhere",
            AgentEvent.topic_id == second_topic.id,
        )
    ).one()
    assert event.detail == note.resolve().as_uri()


def test_descriptor_read_refuses_symlinked_vault_root(tmp_path):
    import os

    from adaptive_academy.engine import vault as vault_mod

    if os.open not in os.supports_dir_fd:
        pytest.skip("dir_fd unsupported")
    real = tmp_path / "real"
    real.mkdir()
    (real / "note.md").write_text("# N\n\nbody", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    # The root passed to the descriptor walk is the symlink itself (a swapped root).
    with pytest.raises(OSError):
        vault_mod._read_text_descriptor(
            link / "note.md", vault=link, limit=10_000, errors="strict"
        )
    # Mtime is taken from the descriptor that was read, not from a second stat().
    text, mtime = vault_mod._read_index_text_with_mtime(real / "note.md", vault=real)
    assert text.startswith("# N")
    assert mtime == (real / "note.md").stat().st_mtime


def test_reindex_progress_counts_read_failures(session, tmp_path):
    from adaptive_academy.engine.vault import reindex_vault

    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    (tmp_path / "ok.md").write_text("# OK\n\nfine", encoding="utf-8")
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00")
    progress = {"indexed": 0, "skipped": 0, "removed": 0}
    result = reindex_vault(session, topic.id, str(tmp_path), progress=progress)
    assert result.skipped >= 1
    assert progress["skipped"] == result.skipped
    assert progress["indexed"] == result.indexed


def test_reindex_vault_expired_deadline_truncates_without_orphan_sweep(
    session,
    tmp_path,
    monkeypatch,
):
    from adaptive_academy.engine import vault as vault_mod

    topic = _topic(session)
    orphan = tmp_path / "orphan.md"
    orphan.write_text("# Orphan\n\nKeep this indexed chunk.", encoding="utf-8")
    assert reindex_vault(session, topic.id, str(tmp_path)).indexed == 1
    orphan_ref = orphan.resolve().as_uri()
    orphan.unlink()
    for index in range(3):
        (tmp_path / f"note-{index}.md").write_text(
            f"# Note {index}\n\nNew content {index}.",
            encoding="utf-8",
        )
    original_read = vault_mod._read_index_text
    reads = 0

    def counting_read(path, *, vault):
        nonlocal reads
        reads += 1
        return original_read(path, vault=vault)

    monkeypatch.setattr(vault_mod, "_read_index_text", counting_read)

    result = reindex_vault(
        session,
        topic.id,
        str(tmp_path),
        deadline=time.perf_counter() - 1,
    )

    assert result.indexed <= 1
    assert reads <= 1
    assert result.truncated is True
    assert session.exec(
        select(Chunk).where(Chunk.source_ref == orphan_ref)
    ).one()


def test_capped_vault_scan_preserves_unseen_notes_and_emits_partial_event(
    session,
    tmp_path,
    monkeypatch,
):
    from adaptive_academy.engine import vault as vault_mod

    monkeypatch.setattr(vault_mod, "_MAX_SCAN_FILES", 2)
    b0 = tmp_path / "b0.md"
    b1 = tmp_path / "b1.md"
    b0.write_text("# B0\n\nFirst existing note.", encoding="utf-8")
    b1.write_text("# B1\n\nSecond existing note.", encoding="utf-8")
    topic = _topic(session)
    first = reindex_vault(session, topic.id, str(tmp_path))
    assert first.indexed == 2

    added = tmp_path / "a.md"
    added.write_text("# A\n\nNew note sorts before both existing notes.", encoding="utf-8")
    second = reindex_vault(session, topic.id, str(tmp_path))

    refs = {
        chunk.source_ref
        for chunk in session.exec(
            select(Chunk).where(Chunk.kind == "vault_note")
        ).all()
    }
    assert refs == {
        added.resolve().as_uri(),
        b0.resolve().as_uri(),
        b1.resolve().as_uri(),
    }
    partial = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:reindex_partial")
    ).all()
    assert len(partial) == 1
    assert partial[0].detail == "scan capped at 2 files; orphan sweep skipped"
    assert second.removed == 0


def test_unchanged_vault_chunks_are_retagged_when_a_concept_appears(session, tmp_path):
    from adaptive_academy.engine.vault import reindex_vault
    from adaptive_academy.models import ChunkConcept, Concept, Track

    topic = Topic(title="Stats")
    session.add(topic)
    session.commit()
    (tmp_path / "bayes.md").write_text(
        "# Notes\n\nBayesian Inference underpins the whole approach.", encoding="utf-8"
    )
    reindex_vault(session, topic.id, str(tmp_path))
    assert session.exec(select(ChunkConcept)).all() == []
    track = Track(topic_id=topic.id, title="Stats")
    session.add(track)
    session.commit()
    session.add(Concept(track_id=track.id, name="Bayesian Inference"))
    session.commit()
    second = reindex_vault(session, topic.id, str(tmp_path))
    assert second.indexed == 0  # text unchanged
    assert len(session.exec(select(ChunkConcept)).all()) == 1


def test_expired_deadline_stops_scan_and_orphan_sweep(session, tmp_path):
    import time

    from adaptive_academy.engine.memory import index_text
    from adaptive_academy.engine.vault import _scan_notes_with_skips, reindex_vault
    from adaptive_academy.models import AgentEvent, Chunk

    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    (tmp_path / "a.md").write_text("# A\n\nbody", encoding="utf-8")
    notes, _rejected, complete = _scan_notes_with_skips(
        tmp_path, vault=tmp_path, deadline=time.perf_counter() - 1
    )
    assert notes == [] and complete is False
    # An orphan chunk for a note that no longer exists must survive an expired sweep.
    index_text(session, kind="vault_note", text="gone", topic_id=topic.id,
               source_ref=(tmp_path / "gone.md").resolve().as_uri())
    session.commit()
    result = reindex_vault(session, topic.id, str(tmp_path), deadline=time.perf_counter() - 1)
    assert result.truncated is True
    assert session.exec(select(Chunk).where(Chunk.text == "gone")).all() != []
    assert session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:reindex_partial")
    ).all()
