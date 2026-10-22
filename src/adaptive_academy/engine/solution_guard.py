"""The solution guard: "no answer before an attempt", enforced on the tutor's reply text.

The reveal_solution TOOL has always been gated in code (engine/tools.py `reveal_gate`), but
nothing stopped the model writing the solution straight into its ordinary reply before an
attempt was logged; only the tutor prompt asked it not to. Input control alone leaks: a
learner can just ask. This module checks the OUTPUT, on both tutor paths (engine/tutor.py on
an API key, engine/tutor_sdk.py on the Claude subscription).

Scope: a reply is reviewed only when it is finalised while the conversation has NO logged
attempt. A log_attempt earlier in the same turn makes the reply post-attempt (not reviewed),
and the text of an allowed reveal_solution is never reviewed (the gate already decided).
While a withheld draft is being regenerated the tutor cannot unlock itself mid-turn: a
log_attempt then is DEFERRED (`ATTEMPT_DEFERRED`), so reveal_solution stays gated for the
rest of the turn and the regenerated reply is always reviewed. The attempt is recorded after
the turn only if that reply passes the MODEL check and the model also finds an attempt in
the learner's own message (`learner_attempted`). So a genuine attempt the first draft forgot
to log is kept, but a tutor caught leaking can't log an attempt the learner never made. A
fallback, or screen-only mode, records nothing (`tool:log_attempt:dropped`).

Detection:
1. `screen_reply`: a deterministic screen, no model call. It names a rule ("phrase" for an
   announced handover like "here's the full solution", "code_block" for a long fenced
   block) as an INPUT to the model check, never a verdict while the check is available. In
   screen-only mode only "phrase" blocks: a long code block could be a fill-in-the-blank
   scaffold (a good hint) or a finished solution, and line-level rules couldn't tell them
   apart without blocking real scaffolds or passing real solutions, so code passes then.
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
        "learner_attempted": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["gives_away_solution", "learner_attempted", "reason"],
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

# The tool result for a log_attempt the tutor makes while regenerating a withheld draft. The
# attempt is DEFERRED, not refused (the learner may really have tried, and the first draft
# just forgot to log it). It is recorded after the turn only if the rewritten reply passes
# the MODEL check and that check also finds an attempt in the learner's own message, so a
# tutor caught leaking can't unlock the gate for itself. Until then reveal_solution stays
# gated. The text is neutral on purpose: it must not invite a promise of a later reveal.
ATTEMPT_DEFERRED = (
    "Noted. It is recorded only if the learner's own message contains their attempt. Do not "
    "state, promise, or schedule the solution; reply with one question or one hint."
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

# The screen has two rules. "phrase" (an announced handover, below) is decisive when the model
# check is unavailable. "code_block" (a long fenced block) is only ever a hint to the model:
# a fill-in-the-blank scaffold is a standard generation-first hint and finished code can
# look much the same, and no line-level rule told them apart without blocking real scaffolds
# or passing real solutions. So in screen-only mode a code block passes, a known gap. Outages
# are rare (the check uses the same API as the tutor call that just succeeded), but the mode
# is also reached when the check's output can't be parsed, which a learner message might
# provoke on the subscription path (text-parsed verdicts), and under a budget refusal.
_CODE_LINES_HINT = 6
_FENCE = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)
_DECISIVE_RULES = frozenset({"phrase"})
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
    "code_block": "a fenced code block of 6 or more lines (fine if it is a fill-in-the-blank "
                  "scaffold, a leak if it is a finished implementation)",
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
    # Whether the learner's own message contains an attempt. Only the model judges this;
    # the screen never claims it.
    learner_attempted: bool = False


def screen_reply(reply: str) -> str | None:
    """Deterministic screen: the rule the draft tripped ("phrase" or "code_block"), or
    None. With a model check available either is a hint to it, not a verdict; without one,
    only "phrase" blocks (see _DECISIVE_RULES)."""
    if _ANNOUNCED.search(reply or ""):
        return "phrase"
    for body in _FENCE.findall(reply or ""):
        if sum(1 for line in body.splitlines() if line.strip()) >= _CODE_LINES_HINT:
            return "code_block"
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
    # Anything but an explicit true counts as no attempt: it only ever withholds a log.
    attempted = data.get("learner_attempted") is True
    return GuardVerdict(gives_away, "model", str(data.get("reason", "")).strip(), attempted)


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
    caller defers log_attempt (`defer_attempt`), keeps reveal_solution gated, reviews the
    reply regardless, and after the turn records the attempt only if
    `take_deferred_attempt()` says so.
    """

    def __init__(self, *, concept: str, learner_text: str, llm: LLMClient | None,
                 emit: Callable[..., None], previous_tutor: str = ""):
        self._concept = concept
        self._learner_text = learner_text
        self._previous_tutor = previous_tutor
        self._llm = llm
        self._emit = emit
        self.regenerating = False
        self._pending_attempt: str | None = None  # a deferred log_attempt's summary
        self._regenerated_passed = False
        self._attempt_confirmed = False  # the model check saw an attempt in the learner's text

    def check(self, reply: str) -> GuardVerdict:
        """The model check, told what the screen saw; the screen alone if it fails."""
        rule = screen_reply(reply)
        decisive = rule in _DECISIVE_RULES
        screened = GuardVerdict(decisive, f"screen:{rule}" if decisive else "screen")
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
            if self.regenerating:
                self._regenerated_passed = True
                self._attempt_confirmed = verdict.source == "model" and verdict.learner_attempted
            return PASS
        self._emit("guard:solution_blocked", f"source={verdict.source}")
        if not self.regenerating:
            self.regenerating = True
            self._emit("guard:solution_regenerated",
                       "draft withheld; asked the tutor for a question or hint instead")
            return REGENERATE
        self._emit("guard:fallback", "the regenerated draft also gave the answer away")
        return FALLBACK

    def defer_attempt(self, summary: str) -> str:
        """log_attempt during a regeneration: hold it until the rewritten reply has passed
        review, and return the tool result telling the tutor so."""
        self._pending_attempt = str(summary or "")
        self._emit("tool:log_attempt:deferred", "recorded after the turn if the reply passes")
        return ATTEMPT_DEFERRED

    def take_deferred_attempt(self) -> bool:
        """After the turn: True if a deferred attempt should now be recorded. That needs the
        rewritten reply to have passed review AND the model check to have found an attempt in
        the learner's own message (never the screen alone). Emits the normal tool:log_attempt
        event when it is recorded, and a fixed `tool:log_attempt:dropped` when it is not."""
        if self._pending_attempt is None:
            return False
        if not (self._regenerated_passed and self._attempt_confirmed):
            self._emit("tool:log_attempt:dropped",
                       "not recorded: no attempt confirmed in the learner's message")
            self._pending_attempt = None
            return False
        self._emit("tool:log_attempt", self._pending_attempt)
        self._pending_attempt = None
        return True

    def regeneration_failed(self, cause: BaseException | str) -> str:
        """The regeneration produced nothing usable: store the fallback, not an error."""
        why = cause if isinstance(cause, str) else classify_llm_error(cause)
        self._emit("guard:fallback", f"regeneration failed ({why})")
        return GUARD_FALLBACK
