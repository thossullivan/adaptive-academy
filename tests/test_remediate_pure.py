from adaptive_academy.models import Item


def test_item_remediation_defaults():
    it = Item(phase_id=1, text="x")
    assert it.added_by == "curriculum"
    assert it.remediation_key == ""
