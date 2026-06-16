# tests/test_track_markdown.py
from adaptive_academy.engine.track_markdown import (
    DeliverableView, ItemView, PhaseView, SidebarView, TrackView,
    track_to_markdown,
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
    assert "## Phase 1 — Build a GPT by hand (Weeks 2-5) · _optional_" in md
    assert "- [x] (watch) Karpathy: Let's build GPT" in md
    assert "- [-] (build) Train a char-level GPT" in md
    assert "- **🎯 Ship:** (repo) nanoGPT-equivalent repo" in md
    assert "  - acceptance: trains end to end" in md
    assert "## Sidebar: Math foundations" in md
    assert "_kind: math_refresh_" in md
