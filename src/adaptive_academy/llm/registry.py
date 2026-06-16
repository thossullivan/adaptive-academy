# Resolve model ids by role, not hardcoded at call sites. Update here on model upgrades.
MODELS = {
    "reasoning": "claude-sonnet-4-6",
    "copy": "claude-haiku-4-5",
}


def get_model(role: str) -> str:
    return MODELS[role]
