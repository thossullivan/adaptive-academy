"""First-run readiness: can this API make LLM calls? (Never echoes the key itself.)"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from adaptive_academy.api.deps import use_agent_sdk
from adaptive_academy.llm.keys import MISSING_KEY_DETAIL, anthropic_key_configured
from adaptive_academy.llm.registry import resolved_models
from adaptive_academy.llm.usage import budget_warnings

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupOut(BaseModel):
    llm_backend: Literal["anthropic", "agent_sdk"]
    llm_ready: bool
    message: str
    # Resolved model id per role (AA_MODEL_REASONING / AA_MODEL_COPY, else the default).
    models: dict[str, str]
    # Configuration problems that don't stop the app but change what it will do (e.g. a
    # daily limit that can't cap an unpriced model, so that model's calls are refused).
    warnings: list[str] = []


@router.get("", response_model=SetupOut)
def get_setup() -> SetupOut:
    models = resolved_models()
    if use_agent_sdk():
        return SetupOut(
            llm_backend="agent_sdk",
            llm_ready=True,
            # Not probed: a host where Claude Code is not logged in still reports ready, and
            # each LLM call then returns a legible "Agent SDK request failed" error.
            message=("Using the Claude Agent SDK backend (your Claude subscription). "
                     "Claude Code must be installed and logged in on this host."),
            models=models,
        )
    # The daily limit only governs API-key calls, so its warnings belong to this backend.
    warnings = budget_warnings()
    if anthropic_key_configured():
        return SetupOut(llm_backend="anthropic", llm_ready=True,
                        message="Anthropic API key configured.", models=models,
                        warnings=warnings)
    return SetupOut(llm_backend="anthropic", llm_ready=False, message=MISSING_KEY_DETAIL,
                    models=models, warnings=warnings)
