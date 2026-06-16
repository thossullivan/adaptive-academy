from adaptive_academy.engine.remediate import build_remediate_prompt


def test_prompt_includes_gaps_level_and_evidence_framing():
    system, user = build_remediate_prompt(
        "softmax", ["omitted: subtract the max"], "low",
        foundation_overview="ov", sources_summary="s1")
    assert "softmax" in user
    assert "omitted: subtract the max" in user
    assert "low" in user.lower()
    assert "low-assistance" in system.lower() or "expertise-reversal" in system.lower()
    assert "project" in system.lower() or "problem-first" in system.lower()
    assert "json" in system.lower()
