"""`just seed` / `aa seed` creates the demo topic, idempotently."""

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from adaptive_academy.db import ensure_fts
from adaptive_academy.demo import DEMO_TITLE
from adaptive_academy.models import Assessment, Topic
from adaptive_academy.seed import seed


def _engine(path):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    ensure_fts(engine)
    return engine


def test_seed_creates_the_demo_topic(tmp_path, capsys):
    engine = _engine(tmp_path / "seed.db")
    seed(engine)
    with Session(engine) as s:
        topics = s.exec(select(Topic)).all()
        assert [(t.title, t.is_demo) for t in topics] == [(DEMO_TITLE, True)]
        assert len(s.exec(select(Assessment)).all()) >= 15
    assert "demo" in capsys.readouterr().out.lower()


def test_seed_is_idempotent_and_coexists_with_real_topics(tmp_path, capsys):
    engine = _engine(tmp_path / "seed.db")
    with Session(engine) as s:
        s.add(Topic(title="My own topic"))
        s.commit()
    seed(engine)
    seed(engine)
    with Session(engine) as s:
        titles = sorted((t.title, t.is_demo) for t in s.exec(select(Topic)).all())
    assert titles == sorted([("My own topic", False), (DEMO_TITLE, True)])
    assert "already" in capsys.readouterr().out.lower()
