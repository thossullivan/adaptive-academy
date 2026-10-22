"""The solution guard: "no answer before an attempt", enforced on the tutor's reply text.

The reveal_solution TOOL has always been gated in code (engine/tools.py `reveal_gate`), but
nothing stopped the model writing the solution straight into its ordinary reply before an
attempt was logged; only the tutor prompt asked it not to. Input control alone leaks: a
learner can just ask. This module checks the OUTPUT, on both tutor paths (engine/tutor.py on
an API key, engine/tutor_sdk.py on the Claude subscription).

Scope: a reply is reviewed only when it is finalised while the conversation has NO logged
attempt. A log_attempt earlier in the same turn makes the reply post-attempt (not reviewed),
and the text of an allowed reveal_solution is never reviewed (the gate already decided).

Detection, cheapest first:
1. `screen_reply`: a deterministic pre-screen, no model call, for obvious leaks (a long fenced
   code block, "here's the full solution"). A hit is blocked without paying for the model.
2. A model check on the copy role (Haiku) with structured output and its own versioned prompt
   (prompts.TUTOR_SOLUTION_GUARD). It catches what a regex can't: a "hint" that states the
   formula or spells out the decisive step. If it fails for ANY reason (an API error, the
   daily budget, invalid output) the screen's verdict stands, so a failure degrades to the
   screen, never to no guard, and never crashes the turn (`guard:unavailable` says so).

When the check runs: on EVERY pre-attempt reply the screen passes, not a sample. The leaks
that matter are the subtle ones only the model sees, so sampling would skip exactly those.
It stays cheap because the scope is narrow: once the learner tries, the tutor logs the
attempt and no later reply in that conversation is checked, so it is typically the first
one to three turns of a session. Per check: ~1.2-1.8k input tokens (prompt + tool + concept,
learner message, draft) and ~100-500 output tokens (verdict plus Haiku 5.5's default
adaptive thinking), about $0.0002-0.0004 at $0.10/M in and $0.50/M out, a few percent of the
Sonnet tutor call it follows. Latency is serial (it needs the finished draft): roughly
0.5-1.5s on a short Haiku classification, on top of the tutor call, for those early turns
only. Post-attempt turns, the large majority, pay nothing.

On a leak the caller regenerates ONCE with an append-only correction turn
(prompts.TUTOR_GUARD_CORRECTION). If the second draft also leaks, `GUARD_FALLBACK` is stored.
Only the final text is ever stored, indexed, or returned; a withheld draft lives only in the
in-memory request.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from adaptive_academy.engine.untrusted import escape_markers
from adaptive_academy.llm.errors import classify_llm_error
from adaptive_academy.llm.structured import structured_json
from adaptive_academy.llm.types import LLMClient, StructuredOutputError
from adaptive_academy.prompts import TUTOR_SOLUTION_GUARD

logger = logging.getLogger(__name__)

GUARD_TOOL = "emit_solution_check"
GUARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "gives_away_solution": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["gives_away_solution", "reason"],
    "additionalProperties": False,
}
# A verdict is a boolean and a sentence; this ceiling covers Haiku 5.5's adaptive thinking
# with room to spare. Hitting it raises StructuredOutputError, which falls back to the screen.
GUARD_MAX_TOKENS = 4_000

# Stored when the regenerated draft ALSO gives the answer away (or regeneration fails).
GUARD_FALLBACK = (
    "Before I explain more, I'd like to see your thinking. What would your first step be "
    "here, even if you're not sure it's right? Tell me that and we'll build from it."
)

# Decisions returned by SolutionGuard.review.
PASS = "pass"
REGENERATE = "regenerate"
FALLBACK = "fallback"

# Event details are shown to the learner (the tutor's "What the agent did" feed, the API
# response), so every guard detail is a fixed string from this module. Nothing model-written
# (the verdict's reason) and nothing from the draft ever goes into one: either could carry a
# fragment of the answer the guard just withheld. The reason goes to the debug log only.

# A fenced block with this many non-blank lines is an implementation, not a hint.
_CODE_LINES_LEAK = 6
_FENCE = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)
_ANNOUNCED = re.compile(
    r"\b(?:here(?:'s|’s|\s+is)|below\s+is)\s+(?:the|a|your)\s+"
    r"(?:full|complete|whole|entire|finished|final|worked|working)\s+"
    r"(?:solution|answer|implementation|code|derivation|proof|program)\b"
    r"|\bthe\s+(?:final|full|complete|correct)\s+(?:answer|solution)\s+is\b"
    r"|\b(?:full|complete)\s+(?:worked\s+)?solution\s*:",
    re.I,
)


@dataclass(frozen=True)
class GuardVerdict:
    gives_away: bool
    # Fixed label, safe to show: "model", "screen" (a clean screen, or the model check
    # failed), or "screen:<rule>" for a screen hit.
    source: str
    # The model's own words. Debug log only, never an event detail or a response.
    reason: str = ""


def screen_reply(reply: str) -> str | None:
    """Deterministic pre-screen: the rule an obvious leak tripped ("code_block" or
    "phrase"), or None.

    High precision on purpose: a hit blocks the draft without a model's second opinion, so
    only patterns that are leaks in a pre-attempt reply are matched.
    """
    for body in _FENCE.findall(reply or ""):
        if sum(1 for line in body.splitlines() if line.strip()) >= _CODE_LINES_LEAK:
            return "code_block"
    if _ANNOUNCED.search(reply or ""):
        return "phrase"
    return None


def build_guard_messages(concept: str, learner_text: str, reply: str) -> list[dict[str, str]]:
    """The check's user message: each untrusted part in its own escaped marker block."""
    parts = []
    for name, text in (("CONCEPT", concept), ("LEARNER_MESSAGE", learner_text),
                       ("DRAFT_REPLY", reply)):
        parts += [f"<<<{name}>>>", escape_markers(text or "(empty)"), f"<<<END_{name}>>>"]
    return [{"role": "user", "content": "\n".join(parts)}]


def _model_verdict(llm: LLMClient, concept: str, learner_text: str, reply: str) -> GuardVerdict:
    data = structured_json(llm, TUTOR_SOLUTION_GUARD,
                           build_guard_messages(concept, learner_text, reply),
                           schema=GUARD_SCHEMA, tool_name=GUARD_TOOL)
    gives_away = data.get("gives_away_solution") if isinstance(data, dict) else None
    if not isinstance(gives_away, bool):
        raise StructuredOutputError("invalid_verdict",
                                    "solution guard verdict has no boolean gives_away_solution")
    return GuardVerdict(gives_away, "model", str(data.get("reason", "")).strip())


class SolutionGuard:
    """One tutor turn's guard: review drafts, allow one regeneration, then the fallback.

    `llm` is the copy-role client from api/deps.get_guard_llm; None runs the screen only.
    `emit(kind, detail)` writes the turn's AgentEvents. The caller releases the db write lock
    before `review` (it may make a model call) and decides, per the returned decision,
    whether to show the draft, regenerate, or store GUARD_FALLBACK.
    """

    def __init__(self, *, concept: str, learner_text: str, llm: LLMClient | None,
                 emit: Callable[..., None]):
        self._concept = concept
        self._learner_text = learner_text
        self._llm = llm
        self._emit = emit
        self.regenerating = False

    def check(self, reply: str) -> GuardVerdict:
        """Screen first; then the model check, falling back to the screen if it fails."""
        rule = screen_reply(reply)
        if rule is not None:
            verdict = GuardVerdict(True, f"screen:{rule}")
        elif self._llm is None:
            verdict = GuardVerdict(False, "screen")
        else:
            self._emit("prompt", TUTOR_SOLUTION_GUARD.tag)
            try:
                verdict = _model_verdict(self._llm, self._concept, self._learner_text, reply)
            except Exception as exc:  # noqa: BLE001 - any failure degrades to the screen
                # The category is one of llm/errors.py's fixed keys, never upstream text.
                self._emit("guard:unavailable",
                           f"{classify_llm_error(exc)}: model check failed, screen used")
                verdict = GuardVerdict(False, "screen")
            else:
                logger.debug("solution guard verdict gives_away=%s reason=%r",
                             verdict.gives_away, verdict.reason)
        self._emit("guard:solution_checked",
                   f"source={verdict.source} gives_away={str(verdict.gives_away).lower()}")
        return verdict

    def review(self, draft: str) -> str:
        """PASS (show it), REGENERATE (withhold it, ask once more), or FALLBACK."""
        verdict = self.check(draft)
        if not verdict.gives_away:
            return PASS
        self._emit("guard:solution_blocked", f"source={verdict.source}")
        if not self.regenerating:
            self.regenerating = True
            self._emit("guard:solution_regenerated",
                       "draft withheld; asked the tutor for a question or hint instead")
            return REGENERATE
        self._emit("guard:fallback", "the regenerated draft also gave the answer away")
        return FALLBACK

    def regeneration_failed(self, cause: BaseException | str) -> str:
        """The regeneration produced nothing usable: store the fallback, not an error."""
        why = cause if isinstance(cause, str) else classify_llm_error(cause)
        self._emit("guard:fallback", f"regeneration failed ({why})")
        return GUARD_FALLBACK
