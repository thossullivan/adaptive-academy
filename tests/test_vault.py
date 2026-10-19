"""Pure core of the Obsidian vault integration: slugs, frontmatter, note scanning,
path-safety, and entity→markdown renderers. All filesystem tests use tmp_path."""

import pytest
from sqlmodel import select

from adaptive_academy.engine.vault import (
    EXPORT_FOLDER,
    export_all_topics,
    export_vault,
    ingest_vault,
    note_summary,
    note_title,
    parse_frontmatter,
    render_concept_note,
    render_frontmatter,
    render_hub_note,
    safe_child,
    safe_vault_dir,
    scan_notes,
    slugify,
)
from adaptive_academy.models import (
    Assessment,
    Concept,
    Item,
    KnowledgeEstimate,
    Phase,
    SourceDoc,
    Topic,
    Track,
)


def _seed_topic(session):
    topic = Topic(title="Build LLMs")
    session.add(topic)
    session.commit()
    session.refresh(topic)
    return topic


def _seed_track(session, topic):
    track = Track(topic_id=topic.id, title="LLMs from scratch", overview="Overview line.")
    session.add(track)
    session.commit()
    session.refresh(track)
    phase = Phase(track_id=track.id, title="Attention", position=0)
    session.add(phase)
    session.commit()
    session.refresh(phase)
    session.add(Item(phase_id=phase.id, text="read attention paper", type="read", position=0))
    c = Concept(track_id=track.id, name="Self-Attention", is_load_bearing=True)
    session.add(c)
    session.commit()
    session.refresh(c)
    return track, c


def test_slugify_normalizes():
    assert slugify("Self-Attention & QKV!") == "self-attention-qkv"
    assert slugify("  Spaced   Out  ") == "spaced-out"
    assert slugify("Already-good") == "already-good"


def test_frontmatter_round_trips_scalars():
    block = render_frontmatter({"title": "Foo", "verdict": "solid"})
    assert block.startswith("---\n") and block.rstrip().endswith("---")
    fm, body = parse_frontmatter(block + "the body")
    assert fm["title"] == "Foo" and fm["verdict"] == "solid"
    assert body.strip() == "the body"


def test_frontmatter_renders_lists():
    block = render_frontmatter({"tags": ["adaptive-academy", "ml"]})
    assert "tags: [adaptive-academy, ml]" in block


def test_parse_frontmatter_absent():
    fm, body = parse_frontmatter("# Heading\n\njust content")
    assert fm == {} and body == "# Heading\n\njust content"


def test_note_title_prefers_frontmatter_then_h1_then_fallback():
    assert note_title("---\ntitle: From FM\n---\n# H1 here\nx", "fb") == "From FM"
    assert note_title("# H1 here\n\nbody", "fb") == "H1 here"
    assert note_title("no heading, just text", "fallback-name") == "fallback-name"


def test_note_summary_prefers_frontmatter_then_first_paragraph():
    assert note_summary("---\nsummary: A crisp line\n---\n# T\nlong body", cap=280) == "A crisp line"
    s = note_summary("# Title\n\nFirst real paragraph here.\n\nSecond.", cap=280)
    assert s == "First real paragraph here."


def test_note_summary_caps_length():
    s = note_summary("x" * 500, cap=100)
    assert len(s) <= 101 and s.endswith("…")


def test_scan_notes_recurses_and_skips_our_folder_and_dotdirs(tmp_path):
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("b")
    (tmp_path / "sub" / "c.txt").write_text("not markdown")
    (tmp_path / "Adaptive Academy").mkdir()
    (tmp_path / "Adaptive Academy" / "exported.md").write_text("ours — skip")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "config.md").write_text("dotdir — skip")

    found = {p.name for p in scan_notes(tmp_path)}
    assert found == {"a.md", "b.md"}


def test_safe_vault_dir_validates(tmp_path):
    assert safe_vault_dir(str(tmp_path)) == tmp_path.resolve()
    with pytest.raises(ValueError):
        safe_vault_dir(str(tmp_path / "does-not-exist"))
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(ValueError):
        safe_vault_dir(str(f))  # a file is not a vault dir


def test_safe_child_blocks_traversal(tmp_path):
    root = tmp_path.resolve()
    child = safe_child(root, "Adaptive Academy", "topic", "note.md")
    assert str(child).startswith(str(root))
    with pytest.raises(ValueError):
        safe_child(root, "..", "escape.md")


def test_render_hub_note_links_concepts_and_embeds_track(tmp_path):
    md = render_hub_note(
        topic_title="Build LLMs",
        overview="An overview line.",
        track_markdown="## Phase 1 — Attention",
        concept_names=["Self-Attention", "Softmax"],
    )
    assert "tags: [adaptive-academy]" in md
    assert "An overview line." in md
    assert "## Phase 1 — Attention" in md
    assert "[[self-attention|Self-Attention]]" in md  # slug-linked, display name preserved


def test_render_concept_note_has_verdict_and_backlink():
    md = render_concept_note(
        name="Self-Attention",
        verdict="solid",
        load_bearing=True,
        summary="Held cold on recall; taught.",
        hub_slug="build-llms",
    )
    fm, _ = parse_frontmatter(md)
    assert fm["verdict"] == "solid" and fm["load_bearing"] == "true"
    assert "[[build-llms]]" in md  # backlink to the topic hub


# --- orchestration (DB <-> files) --------------------------------------------

def test_export_vault_writes_hub_and_concept_notes(session, tmp_path):
    topic = _seed_topic(session)
    _, c = _seed_track(session, topic)
    session.add(KnowledgeEstimate(concept_id=c.id, level="medium"))
    session.add(Assessment(concept_id=c.id, kind="self_explanation", prompt="p", score=0.6,
                           verdict="ok"))
    session.commit()

    res = export_vault(session, topic.id, str(tmp_path))

    base = tmp_path / EXPORT_FOLDER / "build-llms"
    hub = base / "build-llms.md"
    note = base / "Concepts" / "self-attention.md"
    assert hub.exists() and note.exists()
    assert str(hub) in res.written
    hub_text = hub.read_text()
    assert "[[self-attention|Self-Attention]]" in hub_text
    assert "Overview line." in hub_text
    fm, _ = parse_frontmatter(note.read_text())
    assert fm["verdict"] == "medium"


def test_export_concept_unassessed_reads_untested_not_default_high(session, tmp_path):
    """Anti-Goodhart: a default KnowledgeEstimate (level defaults 'high') with no assessments
    must NOT export as 'high' competence — an unverified concept reads 'untested'."""
    topic = _seed_topic(session)
    _, c = _seed_track(session, topic)
    session.add(KnowledgeEstimate(concept_id=c.id))  # level defaults to "high", no assessments
    session.commit()

    export_vault(session, topic.id, str(tmp_path))

    note = tmp_path / EXPORT_FOLDER / "build-llms" / "Concepts" / "self-attention.md"
    fm, _ = parse_frontmatter(note.read_text())
    assert fm["verdict"] == "untested"


def test_export_vault_is_idempotent(session, tmp_path):
    topic = _seed_topic(session)
    _seed_track(session, topic)
    export_vault(session, topic.id, str(tmp_path))
    res2 = export_vault(session, topic.id, str(tmp_path))  # second run must not error
    assert any(w.endswith("build-llms.md") for w in res2.written)


def test_export_vault_rejects_missing_path(session, tmp_path):
    topic = _seed_topic(session)
    with pytest.raises(ValueError):
        export_vault(session, topic.id, str(tmp_path / "no-such-vault"))


def test_ingest_vault_creates_sources_and_skips_our_folder(session, tmp_path):
    topic = _seed_topic(session)
    (tmp_path / "note1.md").write_text("---\ntitle: My Note\nsummary: A crisp summary.\n---\nbody")
    (tmp_path / "note2.md").write_text("# Heading Title\n\nFirst paragraph.")
    (tmp_path / EXPORT_FOLDER).mkdir()
    (tmp_path / EXPORT_FOLDER / "ours.md").write_text("# Ours\nskip")

    res = ingest_vault(session, topic.id, str(tmp_path))

    assert res.count == 2
    srcs = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic.id)).all()
    assert {s.title for s in srcs} == {"My Note", "Heading Title"}
    assert all(s.added_by == "obsidian" and s.angle == "vault" and s.status == "proposed"
               for s in srcs)
    assert all(s.url.startswith("file://") for s in srcs)
    assert next(s for s in srcs if s.title == "My Note").summary == "A crisp summary."


def test_ingest_vault_dedups_on_repeat(session, tmp_path):
    topic = _seed_topic(session)
    (tmp_path / "n.md").write_text("# N\n\nx")
    ingest_vault(session, topic.id, str(tmp_path))
    res2 = ingest_vault(session, topic.id, str(tmp_path))
    assert res2.count == 0
    assert len(session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic.id)).all()) == 1


def test_export_all_topics_writes_every_topic(session, tmp_path):
    t1 = _seed_topic(session)  # "Build LLMs"
    _seed_track(session, t1)
    t2 = Topic(title="Learn Rust")
    session.add(t2)
    session.commit()
    session.refresh(t2)
    session.add(Track(topic_id=t2.id, title="rust", overview="Systems."))
    session.commit()

    res = export_all_topics(session, str(tmp_path))

    assert res.topics == 2
    assert (tmp_path / EXPORT_FOLDER / "build-llms" / "build-llms.md").exists()
    assert (tmp_path / EXPORT_FOLDER / "learn-rust" / "learn-rust.md").exists()
    assert len(res.written) >= 2


def test_export_all_topics_skips_the_demo(session, tmp_path):
    # "Export all" mirrors the learner's own topics; the demo is sample data and must not
    # land in their real vault.
    real = _seed_topic(session)
    _seed_track(session, real)
    demo = Topic(title="Demo: Language models", is_demo=True)
    session.add(demo)
    session.commit()
    session.refresh(demo)
    session.add(Track(topic_id=demo.id, title="demo track", overview="Sample."))
    session.commit()

    res = export_all_topics(session, str(tmp_path))

    assert res.topics == 1
    assert sorted(p.name for p in (tmp_path / EXPORT_FOLDER).iterdir()) == ["build-llms"]
    assert not any("demo" in w for w in res.written)


def test_export_single_demo_topic_is_still_allowed(session, tmp_path):
    demo = Topic(title="Demo topic", is_demo=True)
    session.add(demo)
    session.commit()
    session.refresh(demo)
    session.add(Track(topic_id=demo.id, title="demo track", overview="Sample."))
    session.commit()
    export_vault(session, demo.id, str(tmp_path))
    assert (tmp_path / EXPORT_FOLDER / "demo-topic" / "demo-topic.md").exists()


@pytest.mark.parametrize("kinds", [["artifact_review"], ["artifact_review", "teach",
                                                         "productive_failure"]])
def test_export_concept_without_a_graded_assessment_is_not_the_prior(session, tmp_path, kinds):
    """Same rule as the competence view: the stored estimate is a grade only when a kind that
    writes it (assess.GRADING_KINDS) exists. Shipping or teaching alone leaves the prior."""
    topic = _seed_topic(session)
    _, c = _seed_track(session, topic)
    session.add(KnowledgeEstimate(concept_id=c.id, level="high", confidence=0.5))
    for kind in kinds:
        session.add(Assessment(concept_id=c.id, kind=kind, prompt="p", score=0.9))
    session.commit()

    export_vault(session, topic.id, str(tmp_path))

    note = tmp_path / EXPORT_FOLDER / "build-llms" / "Concepts" / "self-attention.md"
    fm, _ = parse_frontmatter(note.read_text())
    assert fm["verdict"] == "ungraded"
