from dataclasses import dataclass

from adaptive_academy.models import Item

from adaptive_academy.engine.remediate import (
    PlacedItem,
    choose_target_phase,
    gap_key,
    plan_remediation_items,
)


def test_item_remediation_defaults():
    it = Item(phase_id=1, text="x")
    assert it.added_by == "curriculum"
    assert it.remediation_key == ""


def test_gap_key_normalizes():
    assert gap_key("  Omitted required element: Softmax  ") == gap_key(
        "omitted required element: softmax")
    assert gap_key("a   b") == gap_key("a b")
    assert gap_key("X") != gap_key("Y")


def test_plan_skips_already_covered_gaps():
    gaps = ["gap one", "gap two"]
    covered = {gap_key("gap one")}
    proposed = [{"type": "build", "text": "do A"}, {"type": "write", "text": "do B"}]
    items = plan_remediation_items(proposed, "softmax", gaps, covered)
    assert len(items) == 1
    assert isinstance(items[0], PlacedItem)
    assert items[0].remediation_key == gap_key("gap two")
    assert items[0].concept_refs == ["softmax"]
    assert items[0].added_by == "remediation"


def test_plan_is_idempotent_when_all_covered():
    gaps = ["gap one"]
    covered = {gap_key("gap one")}
    assert plan_remediation_items([{"type": "build", "text": "x"}], "c", gaps, covered) == []


def test_plan_falls_back_when_fewer_items_than_gaps():
    gaps = ["alpha", "beta"]
    items = plan_remediation_items([{"type": "build", "text": "only one"}], "c", gaps, set())
    assert len(items) == 2
    assert all(i.text for i in items)
    assert items[0].text == "only one"


def test_plan_maps_item_types_and_defaults_to_build():
    items = plan_remediation_items([{"text": "no type"}], "c", ["g"], set())
    assert items[0].type == "build"


def _phase(statuses):
    @dataclass
    class _P:
        statuses: list

    return _P(statuses)


def test_choose_target_phase_picks_earliest_unfinished():
    phases = [_phase(["done", "done"]), _phase(["done", "todo"]), _phase(["todo"])]
    assert choose_target_phase([p.statuses for p in phases]) == 1


def test_choose_target_phase_falls_back_to_last_when_all_done():
    phases = [_phase(["done"]), _phase(["done"])]
    assert choose_target_phase([p.statuses for p in phases]) == 1


def test_choose_target_phase_empty_phase_counts_as_unfinished():
    assert choose_target_phase([["done"], []]) == 1
    assert choose_target_phase([[]]) == 0
