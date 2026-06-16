# tests/test_curriculum_spacing.py
from adaptive_academy.engine.curriculum import insert_spaced_revisits
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
