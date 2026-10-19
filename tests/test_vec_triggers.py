"""Chunk deletes must work whether or not sqlite-vec is loaded.

`ensure_vec` puts a trigger on `chunk` that deletes the chunk's row from the vec0 table
`chunk_vec`. On a connection without the extension (the memory extra is optional; a plain
`just setup` removes it) that trigger fails every chunk delete with "no such module: vec0",
which 500'd DELETE /api/demo. Without the extension the vec triggers are dropped; when it is
back, `ensure_vec` recreates them and purges vectors whose chunk was deleted meanwhile.
"""

import importlib.util
import struct

import pytest
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine, select

from adaptive_academy import db
from adaptive_academy.demo import build_demo, remove_demo
from adaptive_academy.engine.memory import content_hash, remove_source
from adaptive_academy.models import Chunk, Topic

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("sqlite_vec") is None,
    reason="sqlite-vec optional extra is unavailable",
)


def _engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def _triggers(engine) -> set[str]:
    with engine.connect() as connection:
        return {r[0] for r in connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='trigger'")).all()}


def _vec_ids(engine) -> list[int]:
    with engine.connect() as connection:
        return [r[0] for r in connection.execute(
            text("SELECT chunk_id FROM chunk_vec ORDER BY chunk_id")).all()]


@pytest.fixture
def vec_db(tmp_path):
    """A database file built WITH sqlite-vec: three chunks, each with a vector."""
    url = f"sqlite:///{tmp_path / 'aa.db'}"
    engine = _engine(url)
    SQLModel.metadata.create_all(engine)
    assert db.ensure_fts(engine) is True
    assert db.ensure_vec(engine) is True
    with Session(engine) as session:
        topic = Topic(title="T")
        session.add(topic)
        session.commit()
        for i in range(3):
            body = f"chunk {i}"
            session.add(Chunk(kind="vault_note", topic_id=topic.id, source_ref=f"note:{i}",
                              text=body, content_hash=content_hash(body)))
        session.commit()
        ids = list(session.exec(select(Chunk.id).order_by(Chunk.id)).all())
    with engine.begin() as connection:
        for chunk_id in ids:
            connection.execute(
                text("INSERT INTO chunk_vec(chunk_id, embedding) VALUES (:id, :e)"),
                {"id": chunk_id, "e": struct.pack("<384f", *([0.1] * 384))})
    assert "chunk_vec_ad" in _triggers(engine)
    engine.dispose()
    return url, ids


def _without_vec(monkeypatch, url):
    """A process without the memory extra: sqlite_vec does not import."""
    monkeypatch.setattr(db, "sqlite_vec", None)
    engine = _engine(url)
    assert db.ensure_vec(engine) is False
    return engine


def test_chunk_deletes_work_without_vec_and_vec_rows_are_purged_when_it_returns(
        vec_db, monkeypatch):
    url, ids = vec_db
    real_sqlite_vec = db.sqlite_vec
    plain = _without_vec(monkeypatch, url)
    assert "chunk_vec_ad" not in _triggers(plain)

    with Session(plain) as session:
        assert remove_source(session, "note:0") == 1  # the source-removal path
        session.commit()
    plain.dispose()
    monkeypatch.setattr(db, "sqlite_vec", real_sqlite_vec)  # the extension is back

    vec = _engine(url)
    assert db.ensure_vec(vec) is True
    assert "chunk_vec_ad" in _triggers(vec)
    assert _vec_ids(vec) == ids[1:]  # the deleted chunk's vector is gone
    # ...and the trigger is live again: a delete with vec loaded removes the vector at once.
    with Session(vec) as session:
        remove_source(session, "note:1")
        session.commit()
    assert _vec_ids(vec) == ids[2:]
    vec.dispose()


def test_load_failure_also_drops_the_vec_triggers(vec_db, monkeypatch):
    # sqlite_vec imports but the extension can't load (e.g. a Python built without
    # enable_load_extension): same outcome as not installed.
    url, _ = vec_db

    def cannot_load(_connection, _record):
        raise AttributeError("enable_load_extension")

    monkeypatch.setattr(db, "_load_vec_extension", cannot_load)
    engine = _engine(url)
    assert db.ensure_vec(engine) is False
    assert "chunk_vec_ad" not in _triggers(engine)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM chunk"))
    engine.dispose()


def test_demo_removal_works_without_vec(tmp_path, monkeypatch):
    # The reported failure: the demo's memory chunks were written on a vec-enabled database,
    # then "Remove demo" ran in a process without the extension.
    url = f"sqlite:///{tmp_path / 'demo.db'}"
    engine = _engine(url)
    SQLModel.metadata.create_all(engine)
    db.ensure_fts(engine)
    assert db.ensure_vec(engine) is True
    with Session(engine) as session:
        build_demo(session)
        assert session.exec(select(Chunk)).first() is not None
    engine.dispose()

    plain = _without_vec(monkeypatch, url)
    with Session(plain) as session:
        assert remove_demo(session) is True
        assert session.exec(select(Chunk)).first() is None
    plain.dispose()
