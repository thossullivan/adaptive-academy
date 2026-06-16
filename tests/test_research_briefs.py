from adaptive_academy.engine.research import ANGLES, build_briefs
from adaptive_academy.llm.researcher_types import SearchBrief


def test_build_briefs_count_and_determinism():
    a = build_briefs("Build LLMs from scratch", "learn transformers", 5)
    b = build_briefs("Build LLMs from scratch", "learn transformers", 5)
    assert len(a) == 5
    assert a == b  # deterministic
    assert all(isinstance(x, SearchBrief) for x in a)


def test_build_briefs_caps_to_available_angles():
    out = build_briefs("Topic", "intent", 99)
    assert len(out) == len(ANGLES)


def test_build_briefs_embeds_topic_in_query():
    out = build_briefs("Diffusion models", "intent", 3)
    assert all("Diffusion models" in b.query for b in out)
    assert [b.angle for b in out] == [a[0] for a in ANGLES[:3]]
