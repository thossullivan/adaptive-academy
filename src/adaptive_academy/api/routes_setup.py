"""First-run readiness: can this API make LLM calls? (Never echoes a key itself.)"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from adaptive_academy.llm.backends import BACKEND_AGENT_SDK, api_backend, current_backend_name
from adaptive_academy.llm.keys import key_configured, missing_key_detail
from adaptive_academy.llm.model_catalog import experimental_models
from adaptive_academy.llm.registry import MODEL_ENV_VARS, resolved_models
from adaptive_academy.llm.usage import budget_warnings

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupOut(BaseModel):
    llm_backend: Literal["anthropic", "agent_sdk", "openrouter"]
    # The service the calls go to, named for people: "Anthropic", "OpenRouter", or
    # "Claude subscription" (agent_sdk).
    provider: str
    llm_ready: bool
    message: str
    # The environment variable whose key is missing (ANTHROPIC_API_KEY / OPENROUTER_API_KEY),
    # or None when the backend has what it needs.
    missing_key: str | None = None
    # Resolved model id per role (AA_MODEL_REASONING / AA_MODEL_COPY, else the default).
    models: dict[str, str]
    # Configured models that are not Anthropic Claude models (llm/model_catalog.py): allowed
    # through OpenRouter, but not verified with this app's tools.
    experimental_models: list[str] = []
    experimental_warning: str | None = None
    # Configuration problems that don't stop the app but change what it will do (e.g. a
    # daily limit that can't cap an unpriced model, so that model's calls are refused).
    warnings: list[str] = []


def _experimental_warning(models: dict[str, str], flagged: list[str]) -> str | None:
    if not flagged:
        return None
    settings_named = [MODEL_ENV_VARS[role] for role, model in models.items() if model in flagged]
    names = ", ".join(flagged)
    return (
        f"Experimental model: {names} ({' / '.join(settings_named)}). It is not a Claude "
        "model, so structured answers, web search, and the tutor's tools may not work as "
        "well. Claude models through OpenRouter are fully supported."
    )


@router.get("", response_model=SetupOut)
def get_setup() -> SetupOut:
    models = resolved_models()
    if current_backend_name() == BACKEND_AGENT_SDK:
        return SetupOut(
            llm_backend="agent_sdk",
            provider="Claude subscription",
            llm_ready=True,
            # Not probed: a host where Claude Code is not logged in still reports ready, and
            # each LLM call then returns a legible 502 with category "agent_sdk".
            message=("Using the Claude Agent SDK backend (your Claude subscription). "
                     "Claude Code must be installed and logged in on this host."),
            models=models,
        )
    backend = api_backend()
    flagged = experimental_models()
    common = {
        "llm_backend": backend.name,
        "provider": backend.provider,
        "models": models,
        "experimental_models": flagged,
        "experimental_warning": _experimental_warning(models, flagged),
        # The daily limit only governs API-key calls, so its warnings belong here.
        "warnings": budget_warnings(),
    }
    if key_configured(backend):
        message = f"{backend.provider} API key configured."
        if backend.base_url:
            message += (f" Requests go through {backend.provider} to the model's provider. "
                        "Only providers that don't store prompts are used.")
        return SetupOut(llm_ready=True, message=message, **common)
    return SetupOut(llm_ready=False, message=missing_key_detail(backend.key_env),
                    missing_key=backend.key_env, **common)
