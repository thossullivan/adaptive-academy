# tests/test_track_markdown.py
from adaptive_academy.engine.track_markdown import (
    DeliverableView, ItemView, PhaseView, SidebarView, TrackView,
    markdown_to_track, track_to_markdown,
)


def _sample() -> TrackView:
    return TrackView(
        title="Build LLMs from scratch",
        overview="A first-principles path.",
        phases=[
            PhaseView(
                title="Build a GPT by hand",
                est_hours="Weeks 2-5",
                flags=["optional"],
                items=[
                    ItemView(text="Karpathy: Let's build GPT", type="watch", status="done"),
                    ItemView(text="Train a char-level GPT", type="build", status="doing"),
                ],
                deliverable=DeliverableView(
                    text="nanoGPT-equivalent repo", kind="repo",
                    acceptance_criteria=["trains end to end", "has a writeup"]),
            ),
        ],
        sidebars=[SidebarView(kind="math_refresh", title="Math foundations",
                              body="linear algebra, chain rule")],
    )


def test_track_to_markdown_golden_format():
    md = track_to_markdown(_sample())
    assert "# Build LLMs from scratch" in md
    assert "## Phase 1 — Build a GPT by hand · ⏳ Weeks 2-5 · _optional_" in md
    assert "- [x] (watch) Karpathy: Let's build GPT" in md
    assert "- [-] (build) Train a char-level GPT" in md
    assert "- **🎯 Ship:** (repo) nanoGPT-equivalent repo" in md
    assert "  - acceptance: trains end to end" in md
    assert "## Sidebar: Math foundations" in md
    assert "_kind: math_refresh_" in md


def test_markdown_round_trip_equality():
    original = _sample()
    restored = markdown_to_track(track_to_markdown(original))
    assert restored == original


def test_round_trip_empty_and_multi_phase():
    tv = TrackView(
        title="T", overview="",
        phases=[
            PhaseView(title="P1", items=[ItemView(text="a", type="read")]),
            PhaseView(title="P2", est_hours="1h", flags=["stretch", "parallel_track"],
                      items=[], deliverable=DeliverableView(text="d", kind="blog")),
        ],
        sidebars=[],
    )
    assert markdown_to_track(track_to_markdown(tv)) == tv


def test_round_trip_phase_title_ending_in_parens():
    # A phase title that itself ends in "(...)" must not be mistaken for est_hours.
    tv = TrackView(
        title="T",
        phases=[
            PhaseView(title="Transformers (decoder-only)", items=[
                ItemView(text="read RoPE (Su et al., 2021)", type="read")]),
            PhaseView(title="Scaling (laws)", est_hours="Weeks 9-11",
                      items=[ItemView(text="x", type="build")]),
        ],
    )
    restored = markdown_to_track(track_to_markdown(tv))
    assert restored == tv
    assert restored.phases[0].title == "Transformers (decoder-only)"
    assert restored.phases[0].est_hours == ""
    assert restored.phases[1].est_hours == "Weeks 9-11"


def test_round_trip_sidebar_body_with_structural_lines_and_blanks():
    # A sidebar body containing "## " and "- [ ]" lines and internal blank lines must
    # survive the round-trip (it must not leak a phantom phase or get truncated).
    body = "Refresh:\n\n## attention\n- [ ] softmax(QKᵀ/√d)V\n\nmore notes"
    tv = TrackView(
        title="T",
        phases=[PhaseView(title="P1", items=[ItemView(text="a", type="read")])],
        sidebars=[
            SidebarView(kind="math_refresh", title="Math", body=body),
            SidebarView(kind="reading_list", title="Papers", body="GPT-2\nGPT-3"),
        ],
    )
    restored = markdown_to_track(track_to_markdown(tv))
    assert restored == tv
    assert restored.sidebars[0].body == body
    assert len(restored.phases) == 1  # no phantom phase from the "## attention" line


def test_round_trip_overview_with_internal_blank_lines():
    tv = TrackView(title="T", overview="para one\n\npara two",
                   phases=[PhaseView(title="P1")])
    assert markdown_to_track(track_to_markdown(tv)).overview == "para one\n\npara two"


def test_round_trip_preserves_items_regardless_of_origin():
    from adaptive_academy.engine.track_markdown import (
        ItemView, PhaseView, TrackView, markdown_to_track, track_to_markdown,
    )
    tv = TrackView(title="T", phases=[PhaseView(
        title="P0", items=[ItemView(text="Remediate: gap A", type="build", status="todo")])])
    back = markdown_to_track(track_to_markdown(tv))
    assert back.phases[0].items[0].text == "Remediate: gap A"
    assert back.phases[0].items[0].type == "build"
