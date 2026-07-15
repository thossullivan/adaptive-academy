from adaptive_academy.prompts import (
    ROLEPLAY_DIRECTOR, ROLEPLAY_PERSONA, ROLEPLAY_GRADE, build_roleplay_persona_prompt,
)


def test_prompts_have_tags():
    assert ROLEPLAY_DIRECTOR.tag == "roleplay.director@v1"
    assert ROLEPLAY_PERSONA.tag == "roleplay.persona@v1"
    assert ROLEPLAY_GRADE.tag == "roleplay.grade@v1"


def test_persona_prompt_embeds_brief_and_hides_grading():
    brief = {"persona": "Skeptical VP of Engineering", "goal": "avoid committing",
             "situation": "a cold outbound call", "hidden_objections": ["already have a vendor"],
             "win_conditions": ["agree to a technical eval"], "difficulty": "high"}
    text = build_roleplay_persona_prompt(brief)
    assert "Skeptical VP of Engineering" in text
    assert "cold outbound call" in text
    assert "[[END]]" in text  # end-signal instruction present
    # The persona must not be told to grade or reveal internals.
    assert "score" not in text.lower()
