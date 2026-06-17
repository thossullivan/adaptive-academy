"""Pure core of the Obsidian vault integration: slugs, frontmatter, note scanning,
path-safety, and entity→markdown renderers. All filesystem tests use tmp_path."""

import pytest

from adaptive_academy.engine.vault import (
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
