# tests/test_curriculum_spacing.py
from adaptive_academy.engine.curriculum import (
    MAX_REVISITS_PER_PHASE,
    REVISIT_PREFIX,
    canonicalize_concept_refs,
    insert_spaced_revisits,
    unspaced,
)
from adaptive_academy.engine.track_markdown import ItemView, PhaseView


def _phases():
    return [
        PhaseView(title="P1", items=[ItemView(text="learn attention", type="read",
                                              concept_refs=["self-attention", "softmax"])]),
        PhaseView(title="P2", items=[ItemView(text="build gpt", type="build",
                                              concept_refs=["self-attention"])]),
        PhaseView(title="P3", items=[ItemView(text="pretrain", type="build",
                                              concept_refs=[])]),
    ]


def test_concept_in_one_phase_gets_a_later_revisit():
    phases = insert_spaced_revisits(_phases(), {"softmax"})
    # softmax only in P1 -> a revisit item referencing it is injected into a later phase
    later = [p for p in phases[1:] if any("softmax" in it.concept_refs for it in p.items)]
    assert later, "expected a spaced revisit of softmax in a later phase"
    injected = [it for p in phases for it in p.items if it.text.startswith("Revisit")]
    assert any("softmax" in it.concept_refs and it.type == "write" for it in injected)


def test_already_spaced_concept_is_left_alone():
    before = _phases()
    after = insert_spaced_revisits(before, {"self-attention"})
    # self-attention already appears in P1 and P2 -> no injection
    injected = [it for p in after for it in p.items if it.text.startswith("Revisit")]
    assert injected == []


def test_unreferenced_concept_is_touched_then_no_crash_single_phase():
    one = [PhaseView(title="only", items=[ItemView(text="x", concept_refs=[])])]
    out = insert_spaced_revisits(one, {"ghost"})
    # single phase: cannot space, but should not crash and should touch it once
    refs = [c for p in out for it in p.items for c in it.concept_refs]
    assert "ghost" in refs


def _phases_referencing(phases, concept):
    return [i for i, p in enumerate(phases)
            if any(concept in it.concept_refs for it in p.items)]


def test_concept_only_in_last_phase_is_spaced_into_an_earlier_phase():
    # A concept the LLM put only in the LAST phase must still span 2 phases.
    phases = _phases()
    phases[2].items.append(ItemView(text="late", type="read", concept_refs=["onlylast"]))
    insert_spaced_revisits(phases, {"onlylast"})
    assert len(_phases_referencing(phases, "onlylast")) >= 2


def test_unreferenced_concept_spans_two_phases_when_multiple_phases():
    phases = _phases()
    insert_spaced_revisits(phases, {"ghost"})
    assert len(_phases_referencing(phases, "ghost")) >= 2


def test_spacing_is_idempotent():
    phases = insert_spaced_revisits(_phases(), {"softmax", "ghost"})
    count_before = sum(len(p.items) for p in phases)
    insert_spaced_revisits(phases, {"softmax", "ghost"})
    assert sum(len(p.items) for p in phases) == count_before  # no further injections


# ── Bounded, deduplicated, placed near use ───────────────────────────────────

def _empty(n):
    return [PhaseView(title=f"P{i}", items=[ItemView(text=f"t{i}", concept_refs=[])])
            for i in range(n)]


def _injected(phases):
    return [[it.concept_refs[0] for it in p.items if it.text.startswith(REVISIT_PREFIX)]
            for p in phases]


def test_no_phase_gets_more_than_the_cap():
    phases = _empty(7)
    lb = {f"c{i:02d}" for i in range(12)}
    insert_spaced_revisits(phases, lb)
    per_phase = [len(x) for x in _injected(phases)]
    assert max(per_phase) <= MAX_REVISITS_PER_PHASE, per_phase
    # 12 concepts x 2 touches = 24 > 7 x 2 slots: a concept is placed only when BOTH of its
    # touches fit, so six get two touches each, the last slot stays free, and the other six
    # are reported, never crammed into the first and last phases or left with one touch.
    placed = [c for c in sorted(lb) if _phases_referencing(phases, c)]
    assert all(len(_phases_referencing(phases, c)) == 2 for c in placed)
    assert sum(per_phase) == 12
    assert len(unspaced(phases, lb)) == 6


def test_no_partial_placement_when_only_one_slot_is_free():
    phases = _empty(2)
    phases[1].items += [ItemView(text=REVISIT_PREFIX + "x", type="write", concept_refs=["x"]),
                        ItemView(text=REVISIT_PREFIX + "y", type="write", concept_refs=["y"])]
    insert_spaced_revisits(phases, {"ghost"})
    assert _phases_referencing(phases, "ghost") == []  # not a lone touch in P0
    assert unspaced(phases, {"ghost"}) == ["ghost"]


def test_first_touch_never_lands_after_a_dependent_uses_it():
    phases = _empty(4)
    phases[0].items += [ItemView(text=REVISIT_PREFIX + "x", type="write", concept_refs=["x"]),
                        ItemView(text=REVISIT_PREFIX + "y", type="write", concept_refs=["y"])]
    phases[0].items.append(ItemView(text="use", concept_refs=["dependent"]))
    # P0 (where the dependent is used) is full: introducing the prerequisite in P1-P3 would
    # come after it was needed, so it is not placed at all.
    insert_spaced_revisits(phases, {"prereq"}, dependents={"prereq": {"dependent"}})
    assert _phases_referencing(phases, "prereq") == []


def test_single_reference_after_its_dependent_is_revisited_before_it():
    phases = _empty(5)
    phases[1].items.append(ItemView(text="use", concept_refs=["dependent"]))
    phases[3].items.append(ItemView(text="late intro", concept_refs=["prereq"]))
    insert_spaced_revisits(phases, {"prereq"}, dependents={"prereq": {"dependent"}})
    assert _phases_referencing(phases, "prereq") == [1, 3]


def test_single_phase_track_touches_every_concept_in_one_item():
    one = _empty(1)
    lb = {f"c{i}" for i in range(5)}
    insert_spaced_revisits(one, lb)
    revisits = [it for it in one[0].items if it.text.startswith(REVISIT_PREFIX)]
    assert len(revisits) == 1 and sorted(revisits[0].concept_refs) == sorted(lb)
    assert unspaced(one, lb) == []
    insert_spaced_revisits(one, lb)  # idempotent
    assert len([it for it in one[0].items if it.text.startswith(REVISIT_PREFIX)]) == 1


def test_unspaced_reports_what_the_cap_left_out():
    phases = _empty(2)
    lb = {"a", "b", "c"}
    insert_spaced_revisits(phases, lb, dependents={"c": {"x", "y"}, "a": {"x"}})
    # c (2 dependents) then a (1) take the four slots; b is left unspaced
    assert unspaced(phases, lb) == ["b"]


def test_never_two_revisits_of_one_concept_in_one_phase():
    phases = _empty(3)
    insert_spaced_revisits(phases, {"a", "b"})
    for names in _injected(phases):
        assert len(names) == len(set(names))


def test_unreferenced_prerequisite_lands_just_before_its_first_dependent():
    phases = _empty(6)
    phases[3].items.append(ItemView(text="use", concept_refs=["dependent"]))
    insert_spaced_revisits(phases, {"prereq"}, dependents={"prereq": {"dependent"}})
    assert _phases_referencing(phases, "prereq") == [2, 3]


def test_unreferenced_with_no_referenced_dependent_starts_at_the_first_phase():
    phases = _empty(6)
    insert_spaced_revisits(phases, {"ghost"})
    assert _phases_referencing(phases, "ghost") == [0, 1]


def test_full_target_phase_spills_to_the_next_later_phase():
    phases = _empty(4)
    phases[0].items.append(ItemView(text="intro", concept_refs=["a", "b", "c"]))
    insert_spaced_revisits(phases, {"a", "b", "c"})
    # P1 takes two revisits (cap); the third goes one phase later, not into P0 or massed
    assert sorted(len(x) for x in _injected(phases)) == [0, 0, 1, 2]
    assert len(_injected(phases)[1]) == 2 and len(_injected(phases)[2]) == 1


def test_canonical_refs_resolve_case_and_renames():
    phases = [PhaseView(title="P", items=[
        ItemView(text="x", concept_refs=["Softmax ", "SOFTMAX", "old long: name", "other"])])]
    canonicalize_concept_refs(phases, ["softmax", "short name"],
                              renamed={"old long: name": "short name"})
    assert phases[0].items[0].concept_refs == ["softmax", "short name", "other"]
