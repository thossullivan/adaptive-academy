# Resolve model ids by role, not hardcoded at call sites. The ids come from settings
# (AA_MODEL_REASONING / AA_MODEL_COPY) and are read at call time, so a restarted API picks
# up .env and tests can monkeypatch settings. A blank setting means the backend's default
# (llm/backends.py): Anthropic ids directly, OpenRouter slugs through OpenRouter.
from adaptive_academy import settings as _settings
from adaptive_academy.llm.backends import api_backend

# role → (settings field, env var)
_ROLES = {
    "reasoning": ("reasoning_model", "AA_MODEL_REASONING"),
    "copy": ("copy_model", "AA_MODEL_COPY"),
}
ROLES = tuple(_ROLES)
MODEL_ENV_VARS = {role: env for role, (_, env) in _ROLES.items()}


def get_model(role: str) -> str:
    """Model id for a role. Unknown role → KeyError."""
    field, _ = _ROLES[role]
    # Looked up on the module each call so a swapped-out settings object is honoured too.
    value = getattr(_settings.settings, field, "")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return api_backend().default_models[role]


def resolved_models() -> dict[str, str]:
    """Every role's current model id (role → id)."""
    return {role: get_model(role) for role in ROLES}
