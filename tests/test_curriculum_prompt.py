# tests/test_curriculum_prompt.py
from adaptive_academy.engine.curriculum import build_curriculum_prompt
from adaptive_academy.models import SourceDoc, TopicFoundation, TopicIntent


def test_prompt_encodes_evidence_rules_and_context():
    intent = TopicIntent(topic_id=1, goal="build a GPT", prior_knowledge="strong eng",
                         time_budget="10h/wk")
    fnd = TopicFoundation(topic_id=1, overview="ov",
                          key_concepts=["self-attention", "backprop"],
                          prerequisite_map={"self-attention": ["linear algebra"]})
    sources = [SourceDoc(topic_id=1, title="Attention paper", url="u", tier=1,
                         summary="seminal", status="accepted")]
    system, user = build_curriculum_prompt("Build LLMs", intent, fnd, sources)
    low = system.lower()
    assert "low-assistance" in low or "low assistance" in low
    assert "🎯" in system or "ship" in low
    assert "json" in low
    assert "self-attention" in user and "Attention paper" in user
    assert "10h/wk" in user and "build a GPT" in user
