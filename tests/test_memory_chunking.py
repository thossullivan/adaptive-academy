from sqlmodel import select

from adaptive_academy.engine.memory import (
    WikiLink,
    content_hash,
    extract_wikilinks,
    index_text,
    jaccard,
    make_context,
    normalize,
    remove_source,
    split_markdown,
    split_plain,
)
from adaptive_academy.models import Chunk


def _paragraph(word: str, count: int = 10) -> str:
    return " ".join([word] * count)


def _split_small(text: str):
    return split_plain(text, target=80)


def _chunks_for(session, source_ref: str) -> list[Chunk]:
    return list(
        session.exec(
            select(Chunk).where(Chunk.source_ref == source_ref).order_by(Chunk.ordinal)
        ).all()
    )


def test_normalize_collapses_whitespace_and_uses_nfc_for_hashing():
    assert normalize("  cafe\u0301\n\tlesson  ") == "caf\u00e9 lesson"
    assert content_hash("cafe\u0301 lesson") == content_hash("  caf\u00e9\nlesson ")


def test_split_markdown_keeps_nested_heading_path():
    pieces = split_markdown("# A\n\nParent text.\n\n## B\n\nNested text.")

    assert [piece.heading for piece in pieces] == ["A", "A > B"]
    assert [piece.text for piece in pieces] == ["Parent text.", "Nested text."]
    assert [piece.ordinal for piece in pieces] == [0, 1]


def test_long_markdown_section_splits_on_paragraph_boundaries_without_cutting_words():
    paragraphs = [_paragraph(word, 167) for word in ("alpha", "bravo", "cider")]
    markdown = "# Long\n\n" + "\n\n".join(paragraphs)

    pieces = split_markdown(markdown, target=1200)

    assert len(markdown) >= 3000
    assert len(pieces) >= 3
    assert [piece.text for piece in pieces] == paragraphs
    assert all(piece.heading == "Long" for piece in pieces)


def test_split_markdown_excludes_frontmatter():
    markdown = "---\ntitle: Hidden metadata\ntags: secret\n---\n# Visible\n\nBody text."

    pieces = split_markdown(markdown)

    assert [(piece.heading, piece.text) for piece in pieces] == [("Visible", "Body text.")]
    assert all("Hidden metadata" not in piece.text for piece in pieces)


def test_make_context_joins_document_title_and_heading_path():
    assert make_context("Doc", "A > B") == "Doc > A > B"
    assert make_context("Doc", "") == "Doc"
    assert make_context("", "A > B") == "A > B"


def test_extract_wikilinks_parses_supported_forms_and_skips_fenced_code():
    markdown = """Links: [[T]], [[T|alias]], and [[T#H]].

```python
ignored = "[[CodeTarget]]"
```
"""

    assert extract_wikilinks(markdown) == [
        WikiLink(target="T", alias="", heading=""),
        WikiLink(target="T", alias="alias", heading=""),
        WikiLink(target="T", alias="", heading="H"),
    ]


def test_index_text_stores_meta_on_every_piece_and_skips_unchanged_rows(session):
    source_ref = "test:stable"
    text = "\n\n".join(_paragraph(word) for word in ("alpha", "bravo", "charlie"))
    meta = {"tags": ["memory"], "score": 0.8}

    first = index_text(
        session,
        kind="learner_output",
        text=text,
        source_ref=source_ref,
        doc_title="Doc",
        heading="A > B",
        meta=meta,
        splitter=_split_small,
    )
    initial_chunks = _chunks_for(session, source_ref)
    second = index_text(
        session,
        kind="learner_output",
        text=text,
        source_ref=source_ref,
        doc_title="Doc",
        heading="A > B",
        meta=meta,
        splitter=_split_small,
    )

    assert first.indexed == len(initial_chunks) == 3
    assert first.skipped == first.removed == 0
    assert all(chunk.meta == meta for chunk in initial_chunks)
    assert all(chunk.context == "Doc > A > B" for chunk in initial_chunks)
    assert second.indexed == second.removed == 0
    assert second.skipped == len(initial_chunks)


def test_index_text_updates_only_the_changed_piece_in_place(session):
    source_ref = "test:edited"
    original = [_paragraph(word) for word in ("alpha", "bravo", "charlie")]
    index_text(
        session,
        kind="source_doc",
        text="\n\n".join(original),
        source_ref=source_ref,
        doc_title="Doc",
        source_mtime=1.0,
        splitter=_split_small,
    )
    before = _chunks_for(session, source_ref)
    before_ids = [chunk.id for chunk in before]

    edited = [original[0], _paragraph("delta"), original[2]]
    result = index_text(
        session,
        kind="source_doc",
        text="\n\n".join(edited),
        source_ref=source_ref,
        doc_title="Revised Doc",
        meta={"revision": 2},
        source_mtime=2.0,
        splitter=_split_small,
    )
    after = _chunks_for(session, source_ref)

    assert result.indexed == 1
    assert result.skipped == 2
    assert result.removed == 0
    assert [chunk.id for chunk in after] == before_ids
    assert after[1].text == edited[1]
    assert after[1].context == "Revised Doc"
    assert after[1].meta == {"revision": 2}
    assert after[1].source_mtime == 2.0


def test_index_text_removes_orphans_when_source_gets_shorter(session):
    source_ref = "test:shortened"
    paragraphs = [_paragraph(word) for word in ("alpha", "bravo", "charlie", "delta")]
    index_text(
        session,
        kind="vault_note",
        text="\n\n".join(paragraphs),
        source_ref=source_ref,
        splitter=_split_small,
    )

    result = index_text(
        session,
        kind="vault_note",
        text="\n\n".join(paragraphs[:2]),
        source_ref=source_ref,
        splitter=_split_small,
    )

    assert result.indexed == 0
    assert result.skipped == 2
    assert result.removed == 2
    assert [chunk.ordinal for chunk in _chunks_for(session, source_ref)] == [0, 1]


def test_remove_source_deletes_all_source_chunks_without_committing(session):
    for source_ref in ("test:remove", "test:keep"):
        index_text(
            session,
            kind="question",
            text=_paragraph("one", 11) + "\n\n" + _paragraph("two"),
            source_ref=source_ref,
            splitter=_split_small,
        )

    assert remove_source(session, "test:remove") == 2
    assert _chunks_for(session, "test:remove") == []
    assert len(_chunks_for(session, "test:keep")) == 2


def test_jaccard_uses_normalized_token_sets():
    assert jaccard("the cat sat", "the cat sat down") == 0.75
