"""The solution guard: "no answer before an attempt", enforced on the tutor's reply text.

The reveal_solution TOOL has always been gated in code (engine/tools.py `reveal_gate`), but
nothing stopped the model writing the solution straight into its ordinary reply before an
attempt was logged; only the tutor prompt asked it not to. Input control alone leaks: a
learner can just ask. This module checks the OUTPUT, on both tutor paths (engine/tutor.py on
an API key, engine/tutor_sdk.py on the Claude subscription).

Scope: a reply is reviewed only when it is finalised while the conversation has NO logged
attempt. A log_attempt earlier in the same turn makes the reply post-attempt (not reviewed),
and the text of an allowed reveal_solution is never reviewed (the gate already decided).
While a withheld draft is being regenerated the tutor cannot unlock itself: log_attempt is
refused for that step (`ATTEMPT_REFUSED`; an attempt must come from the learner), so
reveal_solution stays gated and the regenerated reply is always reviewed.

Detection:
1. `screen_reply`: a deterministic screen, no model call, for obvious leaks (a long fenced
   code block that is not a fill-in-the-blank scaffold, "here's the full solution"). It is
   an INPUT to the model check (the model is told which rule fired), never a verdict on its
   own while a model check is available: a Socratic question can trip a keyword.
2. A model check on the copy role (Haiku by default) with structured output and its own
   versioned prompt (prompts.TUTOR_SOLUTION_GUARD). It sees the concept, the tutor's previous
   message (often the question being answered), the learner's message, and the draft, and
   catches what a regex can't: a "hint" that states the formula or the decisive step.
   If it fails for ANY reason (an API error, the daily budget or an unpriced model under it,
   invalid output) the screen alone decides: a failure degrades to the screen, never to no
   guard, and never crashes the turn (`guard:unavailable`, plus one warning per process).

When the check runs: on EVERY pre-attempt reply, not a sample. The leaks that matter are the
subtle ones only the model sees, so sampling would skip exactly those. It stays cheap because
the scope is narrow: once the learner tries, the tutor logs the attempt and no later reply in
that conversation is checked, so it is typically the first one to three turns of a session.

Cost and latency, API-key mode (deps.get_guard_llm -> AnthropicLLMClient on the copy role):
per check ~1.2-2k input tokens (prompt + tool + the four sections, the long ones capped by
`_SECTION_MAX`) and ~100-500 output tokens (verdict plus Haiku 5.5's default adaptive
thinking), about $0.0002-0.0004 at $0.10/M in and $0.50/M out, a few percent of the Sonnet
tutor call it follows. Latency is serial (it needs the finished draft): roughly 0.5-1.5s for
a short Haiku classification, on those early turns only.

Subscription mode (AA_LLM_BACKEND=agent_sdk -> AgentSDKLLMClient): each check is its own
Agent SDK query, which spawns the `claude` CLI, so a check costs several seconds of
wall-clock (CLI start-up plus the model call), not a fraction of one; a regeneration is a
second full tutor query on top. It bills no API credits: it counts against the plan's usage
limits like any other subscription call (llm/usage.py records the SDK's reported cost). That
path has no strict tool, so the verdict is parsed from text and fails to the screen a little
more often.

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

# The tool result for a log_attempt the tutor makes while regenerating a withheld draft.
ATTEMPT_REFUSED = (
    "REFUSED: nothing was recorded. An attempt must come from the learner, in their own "
    "words; you are rewriting a reply that gave the answer away. Reply with one question or "
    "hint that invites their attempt."
)

# Decisions returned by SolutionGuard.review.
PASS = "pass"
REGENERATE = "regenerate"
FALLBACK = "fallback"

# Event details are shown to the learner (the tutor's "What the agent did" feed, the API
# response), so every guard detail is a fixed string from this module. Nothing model-written
# (the verdict's reason) and nothing from the draft ever goes into one: either could carry a
# fragment of the answer the guard just withheld. The reason goes to the debug log only.

# Learner pastes and earlier tutor turns can be huge; the check keeps the head and the tail
# of each (the question usually opens a paste, the ask closes it). The draft is never cut:
# it is the thing being judged, and the tutor's own output is already bounded.
_SECTION_MAX = 6_000

# A fenced block with this many non-blank lines is an implementation, not a hint, unless it
# is a fill-in-the-blank scaffold (TODO, ..., pass, ___), a standard generation-first hint.
_CODE_LINES_LEAK = 6
_FENCE = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)
_SCAFFOLD = re.compile(r"\bTODO\b|\.\.\.|…|_{3,}|^\s*pass\s*$", re.M)
# Only announcements of a handover. A bare "the final answer is" also opens Socratic
# questions ("Before we get to what the final answer is, ..."), so it is not matched.
_ANNOUNCED = re.compile(
    r"\b(?:here(?:'s|’s|\s+is)|below\s+is)\s+(?:the|a|your)\s+"
    r"(?:full|complete|whole|entire|finished|final|worked|working)\s+"
    r"(?:solution|answer|implementation|code|derivation|proof|program)\b"
    r"|\b(?:full|complete)\s+(?:worked\s+)?solution\s*:",
    re.I,
)
# What the model is told when a screen rule fired (our text, outside the untrusted blocks).
_RULE_NOTES = {
    "code_block": "a fenced code block of 6 or more lines that is not a fill-in-the-blank "
                  "scaffold",
    "phrase": "a phrase announcing a full solution or answer",
}

# One warning per process when the guard first degrades to screen-only; every later
# degradation is still traced as a guard:unavailable event.
_warned_degraded = False


@dataclass(frozen=True)
class GuardVerdict:
    gives_away: bool
    # Fixed label, safe to show: "model", "screen" (a clean screen, or the model check
    # failed), or "screen:<rule>" for a screen hit that decided on its own.
    source: str
    # The model's own words. Debug log only, never an event detail or a response.
    reason: str = ""


def screen_reply(reply: str) -> str | None:
    """Deterministic screen: the rule an obvious leak tripped ("code_block" or "phrase"),
    or None. With a model check available this is a hint to it, not a verdict."""
    for body in _FENCE.findall(reply or ""):
        lines = [line for line in body.splitlines() if line.strip()]
        if len(lines) >= _CODE_LINES_LEAK and not _SCAFFOLD.search(body):
            return "code_block"
    if _ANNOUNCED.search(reply or ""):
        return "phrase"
    return None


def _bounded(text: str, limit: int = _SECTION_MAX) -> str:
    """Head and tail of `text`, at most about `limit` characters, with the cut marked."""
    text = text or ""
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = len(text) - 2 * half
    return f"{text[:half]}\n[... {omitted} characters omitted ...]\n{text[-half:]}"


def build_guard_messages(concept: str, learner_text: str, reply: str, *,
                         previous_tutor: str = "",
                         screen_rule: str | None = None) -> list[dict[str, str]]:
    """The check's user message: each untrusted part in its own escaped marker block, and
    (outside them, as our own note) which screen rule fired, if any."""
    sections = [("CONCEPT", concept)]
    if previous_tutor:
        sections.append(("PREVIOUS_TUTOR_MESSAGE", _bounded(previous_tutor)))
    sections += [("LEARNER_MESSAGE", _bounded(learner_text)), ("DRAFT_REPLY", reply)]
    parts = []
    for name, text in sections:
        parts += [f"<<<{name}>>>", escape_markers(text or "(empty)"), f"<<<END_{name}>>>"]
    if screen_rule is not None:
        parts.append(f"SCREEN: the keyword screen flagged the draft for "
                     f"{_RULE_NOTES[screen_rule]}. Look closely; this is not a verdict.")
    return [{"role": "user", "content": "\n".join(parts)}]


def _model_verdict(llm: LLMClient, messages: list[dict[str, str]]) -> GuardVerdict:
    data = structured_json(llm, TUTOR_SOLUTION_GUARD, messages,
                           schema=GUARD_SCHEMA, tool_name=GUARD_TOOL)
    gives_away = data.get("gives_away_solution") if isinstance(data, dict) else None
    if not isinstance(gives_away, bool):
        raise StructuredOutputError("invalid_verdict",
                                    "solution guard verdict has no boolean gives_away_solution")
    return GuardVerdict(gives_away, "model", str(data.get("reason", "")).strip())


def _warn_degraded_once(category: str) -> None:
    global _warned_degraded
    if _warned_degraded:
        return
    _warned_degraded = True
    logger.warning(
        "Solution guard model check failed (%s); using the keyword screen only. Later "
        "failures are traced as guard:unavailable events, not logged again.", category)


class SolutionGuard:
    """One tutor turn's guard: review drafts, allow one regeneration, then the fallback.

    `llm` is the copy-role client from api/deps.get_guard_llm; None runs the screen only.
    `previous_tutor` is the last stored tutor message (the question being answered, often).
    `emit(kind, detail)` writes the turn's AgentEvents. The caller releases the db write lock
    before `review` (it may make a model call) and decides, per the returned decision,
    whether to show the draft, regenerate, or store GUARD_FALLBACK. While `regenerating`, the
    caller refuses log_attempt with ATTEMPT_REFUSED and reviews the reply regardless.
    """

    def __init__(self, *, concept: str, learner_text: str, llm: LLMClient | None,
                 emit: Callable[..., None], previous_tutor: str = ""):
        self._concept = concept
        self._learner_text = learner_text
        self._previous_tutor = previous_tutor
        self._llm = llm
        self._emit = emit
        self.regenerating = False

    def check(self, reply: str) -> GuardVerdict:
        """The model check, told what the screen saw; the screen alone if it fails."""
        rule = screen_reply(reply)
        screened = GuardVerdict(rule is not None, f"screen:{rule}" if rule else "screen")
        if self._llm is None:
            verdict = screened
        else:
            self._emit("prompt", TUTOR_SOLUTION_GUARD.tag)
            messages = build_guard_messages(self._concept, self._learner_text, reply,
                                            previous_tutor=self._previous_tutor,
                                            screen_rule=rule)
            try:
                verdict = _model_verdict(self._llm, messages)
            except Exception as exc:  # noqa: BLE001 - any failure degrades to the screen
                # The category is one of llm/errors.py's fixed keys, never upstream text.
                category = classify_llm_error(exc)
                self._emit("guard:unavailable", f"{category}: model check failed, screen used")
                _warn_degraded_once(category)
                verdict = screened
            else:
                logger.debug("solution guard verdict gives_away=%s screen=%s reason=%r",
                             verdict.gives_away, rule, verdict.reason)
        detail = f"source={verdict.source} gives_away={str(verdict.gives_away).lower()}"
        if rule is not None and verdict.source == "model":
            detail += f" screen={rule}"
        self._emit("guard:solution_checked", detail)
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

    def refuse_attempt(self) -> str:
        """log_attempt during a regeneration: trace it and return the refusal tool result."""
        self._emit("tool:log_attempt:refused", "attempt must come from the learner")
        return ATTEMPT_REFUSED

    def regeneration_failed(self, cause: BaseException | str) -> str:
        """The regeneration produced nothing usable: store the fallback, not an error."""
        why = cause if isinstance(cause, str) else classify_llm_error(cause)
        self._emit("guard:fallback", f"regeneration failed ({why})")
        return GUARD_FALLBACK
