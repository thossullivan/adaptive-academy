from datetime import datetime, timezone

from adaptive_academy import prompts
from adaptive_academy.engine import memory
from adaptive_academy.engine.levels import Levels
from adaptive_academy.llm.retriever_types import Hit
from adaptive_academy.models import Chunk


def _hit(text: str, source_ref: str, *, kind: str = "vault_note") -> Hit:
    return Hit(
        chunk=Chunk(
            kind=kind,
            source_ref=source_ref,
            text=text,
            content_hash=memory.content_hash(text),
            created_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
        ),
        score=1.0,
    )


def test_memory_prompt_versions_and_delimiter_sentences():
    assert prompts.TUTOR_BASE.tag == "tutor.base@v3"
    assert prompts.PF_GENERATE.tag == "practice.pf_generate@v3"
    assert prompts.ROLEPLAY_DIRECTOR.tag == "roleplay.director@v2"
    assert prompts.PAPER_PROBE_DIRECTOR.tag == "paper_probe.director@v2"
    assert prompts.RESEARCH_FOUNDATION.tag == "research.foundation@v3"

    assert prompts.MEMORY_BLOCK_INTRO in prompts.TUTOR_BASE
    assert prompts.MEMORY_BLOCK_INTRO in prompts.PF_GENERATE
    assert prompts.MEMORY_BLOCK_INTRO in prompts.ROLEPLAY_DIRECTOR
    for prompt in (
        prompts.TUTOR_BASE,
        prompts.PF_GENERATE,
        prompts.ROLEPLAY_DIRECTOR,
        prompts.PAPER_PROBE_DIRECTOR,
        prompts.RESEARCH_FOUNDATION,
    ):
        assert prompts.ALREADY_COVERED_INTRO in prompt


def test_tutor_prompt_appends_only_nonempty_memory_blocks():
    levels = Levels(assistance="low", challenge="high")
    plain = prompts.build_tutor_system_prompt("attention", levels)
    enriched = prompts.build_tutor_system_prompt(
        "attention",
        levels,
        memory_block="<<<MEMORY>>>\nsource\n<<<END_MEMORY>>>",
        covered_block=(
            "<<<ALREADY_COVERED>>>\nprior\n<<<END_ALREADY_COVERED>>>"
        ),
    )

    assert plain.endswith("at this difficulty — at \"high\", push to the edge of their "
                          "competence; at \"low\", ease off.")
    assert enriched.endswith("<<<END_ALREADY_COVERED>>>")
    assert "<<<MEMORY>>>\nsource" in enriched
    assert "<<<ALREADY_COVERED>>>\nprior" in enriched


def test_render_block_has_provenance_and_truncates_at_chunk_boundary():
    first = _hit("first complete chunk", "message:1", kind="learner_output")
    first.chunk.meta = {"assessment_kind": "self_explanation", "score": 0.4}
    second = _hit("second complete chunk", "paperprobe:1", kind="paper")
    second.chunk.meta = {"arxiv_id": "1706.03762"}
    second.chunk.heading = "3.2"

    render_block = memory.render_block
    full = render_block([first, second], marker="MEMORY", budget=10_000)
    first_only = render_block([first], marker="MEMORY", budget=10_000)
    truncated = render_block(
        [first, second],
        marker="MEMORY",
        budget=len(first_only) + 1,
    )

    assert "[learner_output · self_explanation · score 0.4 · 2026-07-02]" in full
    assert "[paper · arXiv:1706.03762 · § 3.2]" in full
    assert truncated == first_only
    assert "second complete chunk" not in truncated
    assert len(truncated) <= len(first_only) + 1


def test_render_block_omits_markers_without_a_complete_chunk():
    hit = _hit("a chunk that cannot fit", "vault:1")

    assert memory.render_block([hit], marker="MEMORY", budget=10) == ""
    assert memory.render_block([], marker="MEMORY") == ""
