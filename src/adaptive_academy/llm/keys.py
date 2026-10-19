"""Anthropic API-key lookup, shared by the API-key clients and the /api/setup check.

A missing key used to surface as a bare `KeyError` 500 from client construction. Reading it
here instead gives one definition of "configured" (unset, blank, and the untouched
`.env.example` placeholder all count as missing) and one typed error the API maps to a
legible 503. Nothing here ever returns or logs the key itself outside the client.
"""

import os

# The value shipped in .env.example, plus the example shown in the README and the setup
# notice — copying either without editing it is not a key.
_PLACEHOLDER_KEYS = frozenset({"sk-ant-xxxxx", "sk-ant-...", "sk-ant-…"})

MISSING_KEY_DETAIL = (
    "No ANTHROPIC_API_KEY configured — copy .env.example to .env, set the key, "
    "and restart the API (`just api`)."
)


class MissingAPIKeyError(RuntimeError):
    """No usable ANTHROPIC_API_KEY for an API-key (default backend) LLM client."""

    def __init__(self, message: str = MISSING_KEY_DETAIL):
        super().__init__(message)


def anthropic_key_configured() -> bool:
    """True when ANTHROPIC_API_KEY holds something that could be a real key."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return bool(key) and key not in _PLACEHOLDER_KEYS


def require_anthropic_api_key() -> str:
    """Return the configured key, or raise MissingAPIKeyError (→ 503 at the API layer)."""
    if not anthropic_key_configured():
        raise MissingAPIKeyError()
    return os.environ["ANTHROPIC_API_KEY"].strip()
