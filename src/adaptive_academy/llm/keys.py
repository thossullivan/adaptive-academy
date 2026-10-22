"""API-key lookup, shared by the API-key clients and the /api/setup check.

A missing key used to surface as a bare `KeyError` 500 from client construction. Reading it
here instead gives one definition of "configured" (unset, blank, and the untouched
`.env.example` placeholder all count as missing) and one typed error the API maps to a
legible 503. Each backend (llm/backends.py) names its own variable: ANTHROPIC_API_KEY or
OPENROUTER_API_KEY. Nothing here ever returns or logs the key itself outside the client.
"""

import os

from adaptive_academy.llm.backends import (
    AGENT_SDK_IN_CONTAINER_DETAIL,
    ANTHROPIC,
    Backend,
    agent_sdk_unavailable,
    restart_hint,
)


def missing_key_detail(env_var: str) -> str:
    """The plain fix for a missing key, with the restart step for where the app runs."""
    return (f"No {env_var} is set. Copy .env.example to .env if you haven't, set the key "
            f"in .env, then {restart_hint()}.")


MISSING_KEY_DETAIL = missing_key_detail(ANTHROPIC.key_env)


class MissingAPIKeyError(RuntimeError):
    """No usable key for the API-key LLM clients' backend."""

    def __init__(self, message: str | None = None, *, env_var: str = ANTHROPIC.key_env):
        self.env_var = env_var
        super().__init__(message if message is not None else missing_key_detail(env_var))


class BackendUnavailableError(MissingAPIKeyError):
    """The configured backend can't run here (agent_sdk inside the container). A
    MissingAPIKeyError, so the API maps it to the same legible 503 setup error."""

    def __init__(self, message: str = AGENT_SDK_IN_CONTAINER_DETAIL):
        super().__init__(message, env_var="AA_LLM_BACKEND")


def require_usable_backend() -> None:
    """Raise BackendUnavailableError when the selected backend can't run on this host."""
    if agent_sdk_unavailable():
        raise BackendUnavailableError()


def key_problem(backend: Backend) -> str | None:
    """Why the backend's key variable can't be used, as a plain sentence (never echoing the
    value), or None when it holds something that could be a real key."""
    key = os.environ.get(backend.key_env, "").strip()
    if not key or key in backend.placeholder_keys:
        return missing_key_detail(backend.key_env)
    for prefix, service in backend.foreign_key_prefixes:
        if key.startswith(prefix):
            return (f"{backend.key_env} holds {'an' if service[0] in 'AEIOU' else 'a'} "
                    f"{service} key (it starts with {prefix}). Put your {backend.provider} "
                    f"key in {backend.key_env} in .env, then {restart_hint()}.")
    return None


def key_configured(backend: Backend) -> bool:
    """True when the backend's key variable holds something that could be a real key."""
    return key_problem(backend) is None


def require_api_key(backend: Backend) -> str:
    """Return the backend's key, or raise MissingAPIKeyError (→ 503 at the API layer)."""
    problem = key_problem(backend)
    if problem is not None:
        raise MissingAPIKeyError(problem, env_var=backend.key_env)
    return os.environ[backend.key_env].strip()


def anthropic_key_configured() -> bool:
    """True when ANTHROPIC_API_KEY holds something that could be a real key."""
    return key_configured(ANTHROPIC)


def require_anthropic_api_key() -> str:
    return require_api_key(ANTHROPIC)
