import os
from collections.abc import Iterator

from sqlmodel import Session

from adaptive_academy.db import engine
from adaptive_academy.llm.anchor_types import AnchorClient
from adaptive_academy.llm.anthropic_anchor import AnthropicAnchorClient
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
from adaptive_academy.llm.researcher_types import ResearcherClient
from adaptive_academy.llm.types import LLMClient


def _use_agent_sdk() -> bool:
    """Opt in to the Claude Agent SDK backend (subscription auth) via env flag.

    Default is the API-key client, so nothing changes unless you set this.
    """
    return os.getenv("AA_LLM_BACKEND", "").lower() == "agent_sdk"


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def get_llm() -> LLMClient:
    if _use_agent_sdk():
        from adaptive_academy.llm.agent_sdk_client import AgentSDKLLMClient
        return AgentSDKLLMClient(role="reasoning")
    return AnthropicLLMClient(role="reasoning")


def get_researcher() -> ResearcherClient:
    # In agent_sdk mode, fan out via the SDK's WebSearch tool on the subscription.
    if _use_agent_sdk():
        from adaptive_academy.llm.agent_sdk_researcher import AgentSDKResearcherClient
        return AgentSDKResearcherClient(role="reasoning")
    return AnthropicResearcherClient(role="reasoning")


def get_anchor_client() -> AnchorClient:
    # Anchor generation is a no-tools structured call, so it can run on the subscription
    # by injecting the Agent SDK client into the (transport-agnostic) anchor client.
    if _use_agent_sdk():
        from adaptive_academy.llm.agent_sdk_client import AgentSDKLLMClient
        return AnthropicAnchorClient(llm=AgentSDKLLMClient(role="reasoning"))
    return AnthropicAnchorClient(role="reasoning")
