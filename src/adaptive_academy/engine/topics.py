"""Deleting a topic: every row that belongs to it goes, and what other things own is kept.

`delete_topic` is shared by `DELETE /api/topics/{id}` and the demo's removal (demo.py). It
walks the foreign-key graph down from the topic (`owned_rows`), so a table added later is
covered without touching this module. Three things need more than the walk:

- The memory index. Chunks of the topic's own content are removed through engine/memory.py
  (`remove_source`), and the topic's vault-note chunks with their wikilinks through
  engine/vault.py; the `chunk` delete triggers (db.py) drop each chunk's FTS5 and sqlite-vec
  entries. Chunks of program-owned content (a paper probe, a roleplay) that were filed under
  the topic stay, detached from it: the paper and the roleplay outlive the topic.
- Program links. A milestone slot that started this topic goes back to a stub
  (`topic_id` NULL, status "stub"), so the program keeps the slot and can start it again.
- Files. Nothing on disk is touched: notes exported to the user's Obsidian vault stay there.

LLMUsage rows have no topic column, so cost history (and the Usage page totals) is kept.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import Table, delete, or_, update
from sqlalchemy import select as sa_select
from sqlmodel import Session, SQLModel, col, select

from adaptive_academy.engine.memory import remove_source, take_write_lock
from adaptive_academy.engine.notebook_sync import NOTEBOOK_SYNC
from adaptive_academy.engine.runlock import exclusive_run
from adaptive_academy.engine.vault import _remove_vault_source
from adaptive_academy.models import (
    AgentEvent,
    Chunk,
    Concept,
    Milestone,
    ProgramTopicLink,
    Topic,
    Track,
)

# Chunks whose source row belongs to a program, not to the topic they were filed under
# (engine/memory.py: index_paper, index_paper_answer, index_roleplay_turn, and the roleplay
# opening question). Their source survives the topic, so the chunk does too.
PROGRAM_SOURCE_PREFIXES = ("paperprobe:", "roleplayturn:", "roleplaysession:")


def owned_rows(session: Session, topic_id: int) -> dict[Table, set[int]]:
    """Every row that belongs to the topic: the closure of rows referencing it, through every
    foreign key in the schema (so a table added later is covered without touching this)."""
    tables = SQLModel.metadata.sorted_tables
    referrers: dict[Table, list] = defaultdict(list)
    for table in tables:
        for fk in table.foreign_keys:
            referrers[fk.column.table].append((table, fk.parent))
    topic_table = Topic.__table__
    owned: dict[Table, set[int]] = defaultdict(set)
    owned[topic_table].add(topic_id)
    frontier: list[tuple[Table, set[int]]] = [(topic_table, {topic_id})]
    while frontier:
        table, ids = frontier.pop()
        for child, column in referrers[table]:
            found = set(
                session.execute(sa_select(child.c.id).where(column.in_(ids))).scalars()
            )
            new = found - owned[child]
            if new:
                owned[child] |= new
                frontier.append((child, new))
    return owned


def _clear_memory(session: Session, topic_id: int, concept_ids: set[int]) -> None:
    """Remove the topic's chunks from the memory index; detach program-owned ones."""
    conditions = [Chunk.topic_id == topic_id]
    if concept_ids:
        conditions.append(col(Chunk.concept_id).in_(concept_ids))
    chunks = session.exec(select(Chunk).where(or_(*conditions))).all()
    removals: dict[str, str] = {}
    for chunk in chunks:
        if chunk.source_ref.startswith(PROGRAM_SOURCE_PREFIXES):
            if chunk.topic_id == topic_id:
                chunk.topic_id = None
            if chunk.concept_id in concept_ids:
                chunk.concept_id = None
            session.add(chunk)
        else:
            removals[chunk.source_ref] = chunk.kind
    for source_ref, kind in sorted(removals.items()):
        if kind == "vault_note":
            _remove_vault_source(session, source_ref)  # chunks and their wikilink rows
        else:
            remove_source(session, source_ref)
    session.flush()


def _detach_program_links(session: Session, topic: Topic) -> None:
    """A milestone slot that started this topic becomes a stub again."""
    links = session.exec(
        select(ProgramTopicLink).where(ProgramTopicLink.topic_id == topic.id)
    ).all()
    for link in links:
        link.topic_id = None
        if link.status == "started":
            link.status = "stub"
        session.add(link)
        milestone = session.get(Milestone, link.milestone_id)
        if milestone is not None:
            session.add(AgentEvent(
                program_id=milestone.program_id, kind="program:topic_deleted",
                detail=f"link {link.id}: topic {topic.id} ({topic.title}) deleted; "
                       f"the slot is a {link.status} again"))
    session.flush()


def delete_topic(session: Session, topic_id: int) -> bool:
    """Delete the topic and every row that belongs to it, and commit. False when there is no
    such topic. Raises RunInProgress while its research or curriculum run is going, since that
    run would keep writing rows for the topic."""
    topic = session.get(Topic, topic_id)
    if topic is None:
        return False
    with exclusive_run(f"research:{topic_id}"), exclusive_run(f"curriculum:{topic_id}"):
        # Take the write lock before scanning: a background writer (source indexing, the
        # trace writer) that commits a row for this topic between the scan and the final
        # delete would otherwise make delete(Topic) fail its foreign-key check. From here no
        # other connection can write until the commit below; they wait, then see no topic.
        take_write_lock(session)
        concept_ids = set(session.exec(
            select(Concept.id).join(Track).where(Track.topic_id == topic_id)
        ).all())
        _clear_memory(session, topic_id, concept_ids)
        _detach_program_links(session, topic)

        owned = owned_rows(session, topic_id)
        # Self-references (an assessment's baseline) would block row-by-row deletes.
        for table, ids in owned.items():
            for fk in table.foreign_keys:
                if fk.column.table is table:
                    session.execute(update(table).where(table.c.id.in_(ids))
                                    .values({fk.parent.name: None}))
        # Children before parents, so every delete satisfies foreign_keys=ON as it runs.
        for table in reversed(SQLModel.metadata.sorted_tables):
            ids = owned.get(table)
            if ids:
                session.execute(delete(table).where(table.c.id.in_(ids)))
        session.commit()
    # Its notes' sync problems would keep the Vault page reporting a skipped note for a
    # topic that is gone.
    NOTEBOOK_SYNC.clear_problems(concept_ids)
    return True
