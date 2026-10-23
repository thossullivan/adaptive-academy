import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api import routes_paper_probe
from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_fetcher, get_llm, get_session
from adaptive_academy.engine.memory import (
    ReindexResult,
    index_paper,
    index_source_doc,
    index_text,
    reindex_topic,
)
from adaptive_academy.engine.paper import PaperExtract
from adaptive_academy.engine.vault import reindex_vault
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Chunk,
    Concept,
    Milestone,
    PaperProbe,
    Program,
    ProgramTopicLink,
    SourceDoc,
    Topic,
    Track,
)


def _source_doc(session, *, url: str = "https://arxiv.org/abs/1706.03762") -> SourceDoc:
    topic = Topic(title="Transformers")
    session.add(topic)
    session.flush()
    doc = SourceDoc(topic_id=topic.id, title="Attention", url=url, status="accepted")
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def _paper_context(session) -> tuple[Program, Milestone, Topic]:
    program = Program(title="Program")
    session.add(program)
    session.flush()
    milestone = Milestone(program_id=program.id, title="Read papers")
    session.add(milestone)
    session.flush()
    first = Topic(title="First topic")
    second = Topic(title="Second topic")
    session.add(first)
    session.add(second)
    session.flush()
    session.add(ProgramTopicLink(milestone_id=milestone.id, topic_id=first.id, status="started"))
    session.add(ProgramTopicLink(milestone_id=milestone.id, topic_id=second.id, status="started"))
    session.commit()
    return program, milestone, first


def test_index_source_doc_fetches_text_with_title_heading(session):
    doc = _source_doc(session)

    result = index_source_doc(
        session,
        doc,
        fetch=lambda _: "First paragraph.\n\nSecond paragraph.",
    )
    session.commit()

    chunks = session.exec(select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc.id}")).all()
    assert result.indexed == len(chunks) == 1
    assert chunks[0].kind == "source_doc"
    assert chunks[0].heading == doc.title
    assert chunks[0].topic_id == doc.topic_id


def test_index_source_doc_fetch_exception_is_a_skip(session):
    doc = _source_doc(session)

    def raising_fetch(_: str) -> str:
        raise RuntimeError("offline")

    result = index_source_doc(session, doc, fetch=raising_fetch)
    session.commit()

    assert result.indexed == 0
    assert not session.exec(select(Chunk)).all()
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:fetch_skipped")
    ).one()
    assert event.topic_id == doc.topic_id
    assert "RuntimeError" in event.detail


@pytest.mark.parametrize("fetched", [None, "", "   "])
def test_index_source_doc_empty_fetch_is_a_skip(session, fetched):
    doc = _source_doc(session)

    result = index_source_doc(session, doc, fetch=lambda _: fetched)
    session.commit()

    assert result.indexed == 0
    assert not session.exec(select(Chunk)).all()
    assert session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:fetch_skipped")
    ).one()


def test_vault_source_doc_is_not_indexed_twice(session, tmp_path):
    topic = Topic(title="Vault")
    session.add(topic)
    session.commit()
    path = tmp_path / "local.md"
    path.write_text("# Local\n\nOne indexed copy.", encoding="utf-8")
    reindex_vault(session, topic.id, str(tmp_path))
    doc = SourceDoc(
        topic_id=topic.id,
        title="Local",
        url=path.resolve().as_uri(),
        status="accepted",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    result = index_source_doc(
        session,
        doc,
        fetch=lambda _: pytest.fail("vault documents must not be fetched"),
    )

    assert result.indexed == 0
    assert session.exec(select(Chunk).where(Chunk.kind == "vault_note")).all()
    assert not session.exec(select(Chunk).where(Chunk.kind == "source_doc")).all()


def test_index_paper_uses_first_milestone_topic_and_arxiv_metadata(session):
    program, milestone, first_topic = _paper_context(session)
    probe = PaperProbe(
        program_id=program.id,
        milestone_id=milestone.id,
        paper_title="Attention Is All You Need",
        paper_url="https://arxiv.org/pdf/1706.03762v7.pdf",
        paper_text="# Abstract\n\nTransformer paper.",
    )
    session.add(probe)
    session.flush()

    result = index_paper(session, probe)
    session.commit()

    chunk = session.exec(select(Chunk).where(Chunk.source_ref == f"paperprobe:{probe.id}")).one()
    assert result.indexed == 1
    assert chunk.topic_id == first_topic.id
    assert chunk.heading == "Abstract"
    assert chunk.meta == {
        "arxiv_id": "1706.03762",
        "url": probe.paper_url,
        "title": probe.paper_title,
    }


def test_review_sources_indexes_only_newly_accepted_docs(session):
    doc = _source_doc(session)
    doc.status = "proposed"
    session.add(doc)
    session.commit()
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return "Fetched source text."

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_fetcher] = lambda: fetch
    client = TestClient(app)

    first = client.post(
        f"/api/topics/{doc.topic_id}/sources/review",
        json={"accepted_ids": [doc.id], "pruned_ids": []},
    )
    second = client.post(
        f"/api/topics/{doc.topic_id}/sources/review",
        json={"accepted_ids": [doc.id], "pruned_ids": []},
    )

    assert first.status_code == second.status_code == 200
    assert calls == [doc.url]
    assert session.exec(
        select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc.id}")
    ).one()


def test_review_sources_prune_removes_accepted_source_chunks(session):
    doc = _source_doc(session)
    doc.status = "proposed"
    session.add(doc)
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_fetcher] = lambda: lambda _: "Fetched source text."
    client = TestClient(app)

    accepted = client.post(
        f"/api/topics/{doc.topic_id}/sources/review",
        json={"accepted_ids": [doc.id], "pruned_ids": []},
    )
    assert accepted.status_code == 200
    assert session.exec(
        select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc.id}")
    ).one()

    pruned = client.post(
        f"/api/topics/{doc.topic_id}/sources/review",
        json={"accepted_ids": [], "pruned_ids": [doc.id]},
    )

    assert pruned.status_code == 200
    assert not session.exec(
        select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc.id}")
    ).all()


def test_review_sources_commits_statuses_when_the_fetcher_raises(session):
    doc = _source_doc(session)
    doc.status = "proposed"
    other = SourceDoc(topic_id=doc.topic_id, title="Other", url="https://e.com/o")
    session.add(doc)
    session.add(other)
    session.commit()

    def raising_fetch(_: str) -> str:
        raise RuntimeError("offline")

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_fetcher] = lambda: raising_fetch
    client = TestClient(app)

    resp = client.post(
        f"/api/topics/{doc.topic_id}/sources/review",
        json={"accepted_ids": [doc.id], "pruned_ids": [other.id]},
    )

    assert resp.status_code == 200
    assert {s["id"]: s["status"] for s in resp.json()} == {
        doc.id: "accepted", other.id: "pruned"}
    session.expire_all()
    assert session.get(SourceDoc, doc.id).status == "accepted"
    assert session.get(SourceDoc, other.id).status == "pruned"
    assert not session.exec(select(Chunk)).all()
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:fetch_skipped")
    ).one()
    assert event.topic_id == doc.topic_id
    assert "RuntimeError: offline" in event.detail


def test_review_sources_retries_an_accepted_source_that_was_never_indexed(session):
    """An accepted source with no chunks (its indexing failed or never ran) is queued again on
    the next save; one already indexed is not fetched again."""
    doc = _source_doc(session)  # accepted, never indexed (e.g. the server stopped mid-task)
    indexed = SourceDoc(topic_id=doc.topic_id, title="Indexed", url="https://e.com/i",
                        status="accepted")
    session.add(indexed)
    session.commit()
    index_text(session, kind="source_doc", text="Already indexed text.",
               topic_id=doc.topic_id, source_ref=f"sourcedoc:{indexed.id}")
    session.commit()
    answers = {doc.url: [None, "Fetched on the retry."]}
    calls: list[str] = []

    def fetch(url: str) -> str | None:
        calls.append(url)
        return answers[url].pop(0)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_fetcher] = lambda: fetch
    client = TestClient(app)
    body = {"accepted_ids": [doc.id, indexed.id], "pruned_ids": []}

    first = client.post(f"/api/topics/{doc.topic_id}/sources/review", json=body)
    # Saved again right away: the failed fetch is too recent to try again.
    too_soon = client.post(f"/api/topics/{doc.topic_id}/sources/review", json=body)
    assert calls == [doc.url]
    _age_fetch_skipped_events(session, minutes=11)
    second = client.post(f"/api/topics/{doc.topic_id}/sources/review", json=body)
    third = client.post(f"/api/topics/{doc.topic_id}/sources/review", json=body)

    assert all(r.status_code == 200 for r in (first, too_soon, second, third))
    # Empty the first time (fetch_skipped), retried and indexed once the failure is ten minutes
    # old, then left.
    assert calls == [doc.url, doc.url]
    [chunk] = session.exec(select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc.id}")).all()
    assert chunk.text == "Fetched on the retry."
    assert len(session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:fetch_skipped")).all()) == 1


def _age_fetch_skipped_events(session, *, minutes: int) -> None:
    for event in session.exec(
            select(AgentEvent).where(AgentEvent.kind == "memory:fetch_skipped")).all():
        event.created_at = event.created_at - timedelta(minutes=minutes)
        session.add(event)
    session.commit()


def test_review_sources_does_not_refetch_a_source_whose_fetch_just_failed(session):
    """A paywalled page is not fetched on every save, and the event feed doesn't fill up: a
    source whose last fetch_skipped is under ten minutes old is not queued."""
    doc = _source_doc(session)
    calls: list[str] = []

    def fetch(url: str) -> str | None:
        calls.append(url)
        return None  # a paywall: nothing readable

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_fetcher] = lambda: fetch
    client = TestClient(app)
    body = {"accepted_ids": [doc.id], "pruned_ids": []}

    for _ in range(4):
        assert client.post(f"/api/topics/{doc.topic_id}/sources/review", json=body).status_code \
            == 200
    _age_fetch_skipped_events(session, minutes=9)
    assert client.post(f"/api/topics/{doc.topic_id}/sources/review", json=body).status_code == 200

    assert calls == [doc.url]
    assert len(session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:fetch_skipped")).all()) == 1


def test_index_accepted_sources_logs_an_index_failure_and_keeps_the_status(
    session, monkeypatch
):
    from adaptive_academy.engine import memory

    doc = _source_doc(session)
    second = SourceDoc(topic_id=doc.topic_id, title="Second", url="https://e.com/2",
                       status="accepted")
    session.add(second)
    session.commit()
    real_index_text = memory.index_text

    def flaky_index_text(s, **kw):
        if kw["source_ref"] == f"sourcedoc:{doc.id}":
            raise RuntimeError("disk full")
        return real_index_text(s, **kw)

    monkeypatch.setattr(memory, "index_text", flaky_index_text)

    memory.index_accepted_sources(
        session.get_bind(), [doc.id, second.id], fetch=lambda _: "Fetched source text.")

    session.expire_all()
    assert session.get(SourceDoc, doc.id).status == "accepted"
    refs = {c.source_ref for c in session.exec(select(Chunk)).all()}
    assert refs == {f"sourcedoc:{second.id}"}
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:index_skipped")
    ).one()
    assert event.topic_id == doc.topic_id
    assert "RuntimeError: disk full" in event.detail


def test_index_accepted_sources_skips_a_source_pruned_during_the_fetch(session):
    from adaptive_academy.engine.memory import index_accepted_sources

    doc = _source_doc(session)

    def fetch_then_prune(_: str) -> str:
        session.get(SourceDoc, doc.id).status = "pruned"
        session.commit()
        return "Fetched source text."

    index_accepted_sources(session.get_bind(), [doc.id], fetch=fetch_then_prune)

    assert not session.exec(select(Chunk)).all()


def test_source_and_foundation_output_strip_stored_cite_tags(session):
    from adaptive_academy.models import TopicFoundation

    doc = _source_doc(session)
    doc.summary = "<cite index='20-11,20-12'>The paper starts from</cite> a prior."
    doc.why = '<cite index="1-1">Read</cite> it'
    session.add(doc)
    session.add(TopicFoundation(
        topic_id=doc.topic_id, overview="<cite index='2-1'>Overview</cite>",
        key_concepts=["<cite index='2-2'>attention</cite>"],
        prerequisite_map={"<cite index='2-3'>attention</cite>": ["<cite index='2-4'>dot</cite>"]},
    ))
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)

    [source] = client.get(f"/api/topics/{doc.topic_id}/sources").json()
    foundation = client.get(f"/api/topics/{doc.topic_id}/foundation").json()

    assert source["summary"] == "The paper starts from a prior."
    assert source["why"] == "Read it"
    assert foundation == {
        "overview": "Overview",
        "key_concepts": ["attention"],
        "prerequisite_map": {"attention": ["dot"]},
    }


def test_reindex_topic_removes_stale_chunk_for_nonaccepted_source(session):
    doc = _source_doc(session)
    doc.status = "pruned"
    session.add(doc)
    index_text(
        session,
        kind="source_doc",
        text="Stale source text.",
        source_ref=f"sourcedoc:{doc.id}",
        topic_id=doc.topic_id,
    )
    session.commit()

    result = reindex_topic(
        session,
        doc.topic_id,
        vault_path="",
        fetch=lambda _: pytest.fail("non-accepted sources must not be fetched"),
        kinds=("source_doc",),
    )

    assert result.removed == 1
    assert not session.exec(
        select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc.id}")
    ).all()


def test_start_paper_probe_indexes_arxiv_and_pasted_text(session, monkeypatch):
    program, milestone, topic = _paper_context(session)
    track = Track(topic_id=topic.id, title="Track")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="Attention", is_load_bearing=True)
    session.add(concept)
    session.commit()
    response = LLMResponse(
        text=json.dumps({"questions": [{"axis": "method", "prompt": "How?", "concept_ids": []}]})
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([response, response])
    client = TestClient(app)

    monkeypatch.setattr(
        routes_paper_probe,
        "ingest_paper",
        lambda **_: PaperExtract(
            title="Attention Is All You Need",
            text="# Abstract\n\nFetched paper text.",
            source="arxiv",
        ),
    )
    arxiv = client.post(
        f"/api/programs/{program.id}/milestones/{milestone.id}/paper-probe",
        json={"url": "https://arxiv.org/abs/1706.03762"},
    )
    pasted = client.post(
        f"/api/programs/{program.id}/milestones/{milestone.id}/paper-probe",
        json={"pasted_text": "# Notes\n\nPasted paper text.", "title": "Pasted"},
    )

    assert arxiv.status_code == pasted.status_code == 200
    chunks = session.exec(select(Chunk).where(Chunk.kind == "paper").order_by(Chunk.id)).all()
    assert [chunk.meta["arxiv_id"] for chunk in chunks] == ["1706.03762", ""]


def test_reindex_topic_aggregates_vault_and_accepted_sources(session, tmp_path):
    doc = _source_doc(session)
    (tmp_path / "note.md").write_text("# Note\n\nVault text.", encoding="utf-8")

    result = reindex_topic(
        session,
        doc.topic_id,
        vault_path=str(tmp_path),
        fetch=lambda _: "Source text.",
    )

    assert isinstance(result, ReindexResult)
    assert result.indexed == 2
    assert result.skipped == result.removed == 0
    assert result.truncated is False
    assert result.ms >= 0


def test_reindex_topic_reports_committed_stale_source_removals_in_progress(session):
    from adaptive_academy.engine.memory import index_text, reindex_topic
    from adaptive_academy.models import SourceDoc, Topic

    topic = Topic(title="Sources")
    session.add(topic)
    session.commit()
    doc = SourceDoc(topic_id=topic.id, title="Pruned", url="https://example.org/p", status="pruned")
    session.add(doc)
    session.commit()
    index_text(session, kind="source_doc", text="old source text", topic_id=topic.id,
               source_ref=f"sourcedoc:{doc.id}", doc_title="Pruned")
    session.commit()
    progress = {"indexed": 0, "skipped": 0, "removed": 0}
    result = reindex_topic(session, topic.id, vault_path="", fetch=lambda url: None,
                           kinds=("source_doc",), progress=progress)
    assert result.removed == 1
    assert progress["removed"] == 1


def test_source_reindex_truncates_during_stale_cleanup_without_loading_docs(session, monkeypatch):

    from adaptive_academy.engine.memory import index_text, reindex_topic
    from adaptive_academy.models import SourceDoc, Topic

    topic = Topic(title="Sources")
    session.add(topic)
    session.commit()
    pruned = SourceDoc(topic_id=topic.id, title="Pruned", url="https://example.org/p", status="pruned")
    accepted = SourceDoc(topic_id=topic.id, title="Live", url="https://example.org/a", status="accepted")
    session.add(pruned)
    session.add(accepted)
    session.commit()
    index_text(session, kind="source_doc", text="stale", topic_id=topic.id,
               source_ref=f"sourcedoc:{pruned.id}", doc_title="Pruned")
    session.commit()
    fetched = {"n": 0}

    def fetch(url):
        fetched["n"] += 1
        return "live text"

    # Deadline already expired: stale discovery stops before any batch; accepted docs are
    # never fetched; truncated is reported.
    result = reindex_topic(session, topic.id, vault_path="", fetch=fetch,
                           kinds=("source_doc",), deadline_s=0.0)
    assert result.truncated is True
    assert fetched["n"] == 0


def test_accepted_docs_are_not_loaded_when_the_deadline_passes_after_stale_scan(session, monkeypatch):

    from adaptive_academy.engine import memory as memory_mod
    from adaptive_academy.engine.memory import reindex_topic
    from adaptive_academy.models import SourceDoc, Topic

    topic = Topic(title="Sources")
    session.add(topic)
    session.commit()
    session.add(SourceDoc(topic_id=topic.id, title="Live", url="https://example.org/a", status="accepted"))
    session.commit()
    # The (empty) stale-scan query consumes the whole budget; the doc query must not run.
    ticks = iter([0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    monkeypatch.setattr(memory_mod.time, "perf_counter", lambda: next(ticks, 10.0))
    fetched = {"n": 0}

    def fetch(url):
        fetched["n"] += 1
        return "text"

    result = reindex_topic(session, topic.id, vault_path="", fetch=fetch,
                           kinds=("source_doc",), deadline_s=1.0)
    assert result.truncated is True
    assert fetched["n"] == 0
