"""First-run readiness: can this API make LLM calls? (Never echoes a key itself.)"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from adaptive_academy.engine.assess import current_grading_strictness, grading_strictness_problem
from adaptive_academy.llm.backends import (
    AGENT_SDK_IN_CONTAINER_DETAIL,
    BACKEND_AGENT_SDK,
    BACKEND_OPENROUTER,
    agent_sdk_unavailable,
    api_backend,
    backend_setting_problem,
    current_backend_name,
)
from adaptive_academy.llm.keys import key_problem, missing_key_detail
from adaptive_academy.llm.model_catalog import experimental_models, is_openrouter_slug
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
    # When that variable is set but can't be used (e.g. it holds the other service's key), the
    # reason in plain words; None when it is simply missing.
    key_hint: str | None = None
    # Resolved model id per role (AA_MODEL_REASONING / AA_MODEL_COPY, else the default).
    models: dict[str, str]
    # Configured models that are not Anthropic Claude models (llm/model_catalog.py): allowed
    # through OpenRouter, but not verified with this app's tools.
    experimental_models: list[str] = []
    experimental_warning: str | None = None
    # Daily-limit problems that don't stop the app but change what it will do (e.g. a limit
    # that can't cap an unpriced model, so that model's calls are refused).
    warnings: list[str] = []
    # Other configuration that is probably a mistake: a mistyped AA_LLM_BACKEND, a model id
    # that isn't an OpenRouter id on the OpenRouter backend, an unknown AA_GRADING_STRICTNESS.
    setup_warnings: list[str] = []
    # The level answers are graded at (AA_GRADING_STRICTNESS; an unknown value is standard).
    grading_strictness: Literal["lenient", "standard", "strict"] = "standard"


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


def _setup_warnings(backend_name: str, models: dict[str, str]) -> list[str]:
    out = [w for w in [backend_setting_problem(), grading_strictness_problem()] if w]
    if backend_name == BACKEND_OPENROUTER:
        for role, model in models.items():
            if not is_openrouter_slug(model):
                out.append(
                    f"{MODEL_ENV_VARS[role]} is '{model}', which is not an OpenRouter model id. "
                    "OpenRouter ids look like vendor/model, for example "
                    "anthropic/claude-sonnet-5.5. Change it in .env and restart the API.")
    return out


@router.get("", response_model=SetupOut)
def get_setup() -> SetupOut:
    models = resolved_models()
    grading: dict = {"grading_strictness": current_grading_strictness()}
    if current_backend_name() == BACKEND_AGENT_SDK:
        # The grading level applies on every backend, and so does its warning.
        grading["setup_warnings"] = [w for w in [grading_strictness_problem()] if w]
        if agent_sdk_unavailable():
            # The container has no Claude Code: say so, and don't quietly use an API key.
            return SetupOut(llm_backend="agent_sdk", provider="Claude subscription",
                            llm_ready=False, message=AGENT_SDK_IN_CONTAINER_DETAIL,
                            models=models, **grading)
        return SetupOut(
            llm_backend="agent_sdk",
            provider="Claude subscription",
            llm_ready=True,
            # Not probed: a host where Claude Code is not logged in still reports ready, and
            # each LLM call then returns a legible 502 with category "agent_sdk".
            message=("Using the Claude Agent SDK backend (your Claude subscription). "
                     "Claude Code must be installed and logged in on this host."),
            models=models,
            **grading,
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
        "setup_warnings": _setup_warnings(backend.name, models),
        "grading_strictness": grading["grading_strictness"],
    }
    problem = key_problem(backend)
    if problem is None:
        message = f"{backend.provider} API key configured."
        if backend.base_url:
            message += (f" Requests go through {backend.provider} to the model's provider. "
                        "Providers that may train on your prompts are left out.")
        return SetupOut(llm_ready=True, message=message, **common)
    hint = None if problem == missing_key_detail(backend.key_env) else problem
    return SetupOut(llm_ready=False, message=problem, missing_key=backend.key_env,
                    key_hint=hint, **common)
