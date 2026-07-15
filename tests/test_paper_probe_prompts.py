from adaptive_academy.prompts import PAPER_PROBE_DIRECTOR, PAPER_PROBE_OUTCOME


def test_tags():
    assert PAPER_PROBE_DIRECTOR.tag == "paper_probe.director@v1"
    assert PAPER_PROBE_OUTCOME.tag == "paper_probe.outcome@v1"


def test_director_names_markers_and_output_shape():
    assert "<<<PAPER>>>" in PAPER_PROBE_DIRECTOR and "<<<END_PAPER>>>" in PAPER_PROBE_DIRECTOR
    assert "concept_ids" in PAPER_PROBE_DIRECTOR
    assert "axis" in PAPER_PROBE_DIRECTOR


def test_outcome_names_markers():
    assert "<<<ANSWERS>>>" in PAPER_PROBE_OUTCOME and "<<<END_ANSWERS>>>" in PAPER_PROBE_OUTCOME
