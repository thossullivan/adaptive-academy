from adaptive_academy.engine.anchors import parse_anchors_json
from adaptive_academy.llm.anchor_types import AnchorBrief, RawAnchor
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.prompts import ANCHOR


def _build_user_msg(brief: AnchorBrief) -> str:
    lines = [f"SOURCE TITLE: {brief.title}", f"URL: {brief.url}",
             f"SOURCE SUMMARY: {brief.summary}",
             f"TOPIC KEY CONCEPTS: {', '.join(brief.key_concepts)}"]
    return "\n".join(lines)


class AnthropicAnchorClient:
    """Generates anchors for one source via a single structured LLM completion."""

    def __init__(self, *, role: str = "reasoning", llm: LLMClient | None = None):
        self._llm = llm if llm is not None else AnthropicLLMClient(role=role)

    def generate(self, brief: AnchorBrief) -> list[RawAnchor]:
        resp = self._llm.complete(
            system=ANCHOR,
            messages=[{"role": "user", "content": _build_user_msg(brief)}], tools=[])
        return parse_anchors_json(resp.text)
