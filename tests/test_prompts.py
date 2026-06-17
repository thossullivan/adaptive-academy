from adaptive_academy import prompts
from adaptive_academy.engine.levels import Levels
from adaptive_academy.prompts import GRADE, STORY, Prompt, build_tutor_system_prompt


def test_prompt_is_a_str_with_metadata():
    p = Prompt("demo.thing", 3, "hello world")
    assert isinstance(p, str)
    assert p == "hello world"  # drops in anywhere a system string is expected
    assert p.name == "demo.thing"
    assert p.version == 3
    assert p.tag == "demo.thing@v3"


def test_registry_prompts_have_tags():
    assert GRADE.tag == "assess.grade@v1"
    assert STORY.tag == "story.compose@v1"
    # The skeptical-grader phrasing the assessor relies on is preserved.
    assert "SKEPTICAL grader" in GRADE


def test_every_registry_prompt_is_named_and_versioned():
    found = [v for v in vars(prompts).values() if isinstance(v, Prompt)]
    assert len(found) >= 14
    for p in found:
        assert p.name and isinstance(p.version, int) and p.version >= 1


def test_build_tutor_system_prompt_still_composes():
    out = build_tutor_system_prompt("self-attention", Levels(assistance="high", challenge="low"))
    assert "self-attention" in out and "Assistance level = high" in out
