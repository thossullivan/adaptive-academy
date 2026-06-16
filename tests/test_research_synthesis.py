import json

from adaptive_academy.engine.research import Foundation, synthesize_foundation
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse


def _payload() -> str:
    return json.dumps(
        {
            "overview": "Transformers use attention.",
            "key_concepts": ["self-attention", "softmax"],
            "prerequisite_map": {"self-attention": ["dot product"]},
        }
    )


def test_synthesize_parses_plain_json():
    llm = ScriptedLLMClient([LLMResponse(text=_payload())])
    f = synthesize_foundation("LLMs", "learn", [RawSource(title="A", url="a", tier=1)], llm)
    assert isinstance(f, Foundation)
    assert f.overview == "Transformers use attention."
    assert f.key_concepts == ["self-attention", "softmax"]
    assert f.prerequisite_map == {"self-attention": ["dot product"]}


def test_synthesize_strips_markdown_fences():
    llm = ScriptedLLMClient([LLMResponse(text="```json\n" + _payload() + "\n```")])
    f = synthesize_foundation("LLMs", "learn", [], llm)
    assert f.key_concepts == ["self-attention", "softmax"]


def test_synthesize_includes_sources_in_prompt():
    llm = ScriptedLLMClient([LLMResponse(text=_payload())])
    synthesize_foundation("LLMs", "learn", [RawSource(title="Attention Paper", url="u", tier=1)], llm)
    sent = llm.calls[0]["messages"][0]["content"]
    assert "Attention Paper" in sent
