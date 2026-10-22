# tests/test_integration_loop.py
import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_guard_llm, get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse


def test_research_to_curriculum_to_tutor(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "foundational_papers": [RawSource(title="Attention",
            url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.95, summary="s")],
    })
    # 1 LLM call for foundation synthesis, 1 for curriculum, then tutor replies.
    foundation_json = json.dumps({"overview": "o", "key_concepts": ["self-attention", "la"],
                                  "prerequisite_map": {"self-attention": ["la"]}})
    curriculum_json = json.dumps({"overview": "ov", "phases": [
        {"title": "P1", "items": [{"type": "build", "text": "nanoGPT",
                                   "concept_refs": ["self-attention"]}],
         "deliverable": {"kind": "repo", "text": "repo", "acceptance_criteria": ["trains"]}}],
        "sidebars": []})
    # ONE shared client; responses are consumed in sequence across requests:
    # research foundation synth -> curriculum generation -> tutor turn.
    shared_llm = ScriptedLLMClient([
        LLMResponse(text=foundation_json),
        LLMResponse(text=curriculum_json),
        LLMResponse(text="What have you tried so far?"),  # tutor turn (no tool calls)
    ])
    app.dependency_overrides[get_llm] = lambda: shared_llm
    app.dependency_overrides[get_guard_llm] = lambda: ScriptedLLMClient([
        LLMResponse(text='{"gives_away_solution": false, "reason": "asks a question"}'),
    ])
    client = TestClient(app)

    tid = client.post("/api/topics", json={"title": "Build LLMs", "goal": "build a GPT"}).json()["id"]
    client.post(f"/api/topics/{tid}/research")
    sources = client.get(f"/api/topics/{tid}/sources").json()
    client.post(f"/api/topics/{tid}/sources/review",
                json={"accepted_ids": [s["id"] for s in sources], "pruned_ids": []})

    cur = client.post(f"/api/topics/{tid}/curriculum").json()
    concept_id = cur["concepts"][0]["id"]

    convo = client.post("/api/conversations", json={"topic_id": tid, "concept_id": concept_id}).json()
    assert convo["assistance_level"] == "low"  # generated estimate level=high -> low assistance
    reply = client.post(f"/api/conversations/{convo['id']}/messages",
                        json={"content": "explain attention"}).json()
    assert reply["reply"]
    app.dependency_overrides.clear()
