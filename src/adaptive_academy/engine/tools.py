# Tool schemas (Anthropic tool-use format) + tier table.
# Tiers: "auto" executes immediately; "gated" is blocked until attempt_logged is True.

LOG_ATTEMPT = {
    "name": "log_attempt",
    "description": (
        "Record that the learner has made a genuine attempt or explanation. "
        "Call this as soon as the learner tries, even partially."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}

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

TOOLS = [LOG_ATTEMPT, REVEAL_SOLUTION]
TIERS = {"log_attempt": "auto", "reveal_solution": "gated"}
