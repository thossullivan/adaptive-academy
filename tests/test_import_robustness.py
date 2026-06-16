from adaptive_academy.engine.track_markdown import (
    PhaseView,
    TrackView,
    _infer_type,
    markdown_to_track,
    track_to_markdown,
)


def test_infer_type_keywords():
    assert _infer_type("3Blue1Brown Neural Networks series") == "watch"
    assert _infer_type("Karpathy lecture video") == "watch"
    assert _infer_type("Build a GPT by hand") == "build"
    assert _infer_type("Implement LoRA from scratch") == "build"
    assert _infer_type("Train a char-level GPT on TinyShakespeare") == "build"
    assert _infer_type("Write a blog post about attention") == "write"
    assert _infer_type("Read Attention Is All You Need") == "read"
    assert _infer_type("Raschka Ch 3 — Coding attention mechanisms") == "build"


def test_untyped_checkbox_items_parse_with_inferred_type():
    md = """# T

## Phase 0 — Intuition (Week 1)
- [ ] Read *Attention Is All You Need*
- [ ] 3Blue1Brown transformers video
- [x] Implement micrograd from scratch
"""
    tv = markdown_to_track(md)
    assert len(tv.phases) == 1
    items = tv.phases[0].items
    assert [i.type for i in items] == ["read", "watch", "build"]
    assert items[0].text == "Read *Attention Is All You Need*"
    assert items[2].status == "done"  # [x]


def test_heading_with_items_is_phase_prose_heading_is_sidebar():
    md = """# T

## How to use this
- Realistic cadence: ~8-12 hrs/week
Some prose about the plan.

## Math foundations
- [ ] Linear algebra — the big one
- [ ] Calculus / chain rule

## Track B — Small Models & Edge
- [ ] TinyStories replication
"""
    tv = markdown_to_track(md)
    phase_titles = [p.title for p in tv.phases]
    sidebar_titles = [s.title for s in tv.sidebars]
    # "How to use this" has no checkbox items -> sidebar (prose preserved).
    assert "How to use this" in sidebar_titles
    assert any("Realistic cadence" in s.body for s in tv.sidebars)
    # Content sections with checkbox items -> phases (items kept).
    assert "Math foundations" in phase_titles
    assert "Track B — Small Models & Edge" in phase_titles
    math = next(p for p in tv.phases if p.title == "Math foundations")
    assert len(math.items) == 2


def test_canonical_round_trip_unchanged_incl_ship_only_phase():
    # A canonical phase whose ONLY content is a Ship must stay a phase (matches "Phase N —"),
    # not get reclassified as a sidebar.
    from adaptive_academy.engine.track_markdown import DeliverableView, ItemView
    tv = TrackView(title="T", overview="ov", phases=[
        PhaseView(title="Build it", est_hours="8h", items=[
            ItemView(text="read the paper", type="read", status="todo")],
            deliverable=DeliverableView(text="ship a repo", kind="repo",
                                        acceptance_criteria=["it runs"])),
        PhaseView(title="Ship only", deliverable=DeliverableView(
            text="write a blog", kind="blog", acceptance_criteria=["published"])),
    ])
    back = markdown_to_track(track_to_markdown(tv))
    assert [p.title for p in back.phases] == ["Build it", "Ship only"]
    assert back.phases[0].items[0].type == "read"
    assert back.phases[1].deliverable is not None
    assert back.sidebars == []


def test_item_with_parenthetical_prefix_not_misread_as_type():
    md = """# T

## Phase 0 — x
- [ ] (optional, pure first-principles) Karpathy micrograd — build an autograd engine
"""
    tv = markdown_to_track(md)
    it = tv.phases[0].items[0]
    # "(optional, ...)" is not a single-word type, so the whole text is kept and type inferred.
    assert it.text.startswith("(optional, pure first-principles)")
    assert it.type == "build"
