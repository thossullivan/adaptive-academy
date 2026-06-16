from adaptive_academy.engine.anchors import parse_anchors_json
from adaptive_academy.llm.anchor_types import AnchorBrief, RawAnchor
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.types import LLMClient

_ANCHOR_SYSTEM = (
    "You write grounded quiz anchors for an ADVANCED self-directed learner, from ONE "
    "accepted source. Produce questions whose ANSWERS are checkable against the source's "
    "substance — not trivia. For each, give a concise reference_answer and 3-6 short, "
    "literal key_points (terms/expressions a correct answer must contain), and tag the most "
    "relevant concept from the provided list. Respond with ONLY a JSON object: "
    '{"anchors": [{"question": str, "reference_answer": str, "key_points": [str], '
    '"concept": str}]}. 1-3 anchors. No prose outside the JSON.'
)


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
            system=_ANCHOR_SYSTEM,
            messages=[{"role": "user", "content": _build_user_msg(brief)}], tools=[])
        return parse_anchors_json(resp.text)
