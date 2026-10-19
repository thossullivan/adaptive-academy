"""First-run readiness: can this API make LLM calls? (Never echoes the key itself.)"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from adaptive_academy.api.deps import use_agent_sdk
from adaptive_academy.llm.keys import MISSING_KEY_DETAIL, anthropic_key_configured

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupOut(BaseModel):
    llm_backend: Literal["anthropic", "agent_sdk"]
    llm_ready: bool
    message: str


@router.get("", response_model=SetupOut)
def get_setup() -> SetupOut:
    if use_agent_sdk():
        return SetupOut(
            llm_backend="agent_sdk",
            llm_ready=True,
            # Not probed: a host where Claude Code is not logged in still reports ready, and
            # each LLM call then returns a legible "Agent SDK request failed" error.
            message=("Using the Claude Agent SDK backend (your Claude subscription). "
                     "Claude Code must be installed and logged in on this host."),
        )
    if anthropic_key_configured():
        return SetupOut(llm_backend="anthropic", llm_ready=True,
                        message="Anthropic API key configured.")
    return SetupOut(llm_backend="anthropic", llm_ready=False, message=MISSING_KEY_DETAIL)
