"""API-key lookup, shared by the API-key clients and the /api/setup check.

A missing key used to surface as a bare `KeyError` 500 from client construction. Reading it
here instead gives one definition of "configured" (unset, blank, and the untouched
`.env.example` placeholder all count as missing) and one typed error the API maps to a
legible 503. Each backend (llm/backends.py) names its own variable: ANTHROPIC_API_KEY or
OPENROUTER_API_KEY. Nothing here ever returns or logs the key itself outside the client.
"""

import os

from adaptive_academy.llm.backends import ANTHROPIC, Backend


def missing_key_detail(env_var: str) -> str:
    return (
        f"No {env_var} configured — copy .env.example to .env, set the key, "
        "and restart the API (`just api`)."
    )


MISSING_KEY_DETAIL = missing_key_detail(ANTHROPIC.key_env)


class MissingAPIKeyError(RuntimeError):
    """No usable key for the API-key LLM clients' backend."""

    def __init__(self, message: str | None = None, *, env_var: str = ANTHROPIC.key_env):
        self.env_var = env_var
        super().__init__(message if message is not None else missing_key_detail(env_var))


def key_configured(backend: Backend) -> bool:
    """True when the backend's key variable holds something that could be a real key."""
    key = os.environ.get(backend.key_env, "").strip()
    return bool(key) and key not in backend.placeholder_keys


def require_api_key(backend: Backend) -> str:
    """Return the backend's key, or raise MissingAPIKeyError (→ 503 at the API layer)."""
    if not key_configured(backend):
        raise MissingAPIKeyError(env_var=backend.key_env)
    return os.environ[backend.key_env].strip()


def anthropic_key_configured() -> bool:
    """True when ANTHROPIC_API_KEY holds something that could be a real key."""
    return key_configured(ANTHROPIC)


def require_anthropic_api_key() -> str:
    return require_api_key(ANTHROPIC)
