# Tool schemas (Anthropic tool-use format) + tier table.
# Tiers: "auto" executes immediately; "gated" is blocked until attempt_logged is True.
# The tutor has no tool that logs an attempt: only the learner can, with the Submit attempt
# button (engine/attempt.py), so the tutor can never open the gate for itself.

REVEAL_SOLUTION = {
    "name": "reveal_solution",
    "description": (
        "Reveal a full worked solution / final answer. Only permitted AFTER the learner "
        "has logged an attempt. If no attempt has been logged, this call is blocked and "
        "you must give a hint instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}

TOOLS = [REVEAL_SOLUTION]
TIERS = {"reveal_solution": "gated"}

_BLOCKED_MSG = (
    "BLOCKED: the learner has not logged an attempt yet. Do NOT reveal the solution. "
    "Give a single hint or Socratic question instead."
)


def reveal_gate(attempt_logged: bool) -> tuple[bool, str]:
    """The attempt-gate (single source of truth): reveal_solution is permitted only after
    the learner has logged an attempt. Used by both the raw-API tutor loop and the Agent
    SDK tutor's tool handler."""
    if not attempt_logged:
        return False, _BLOCKED_MSG
    return True, "ok: solution permitted"
