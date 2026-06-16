from collections.abc import Iterator

from sqlmodel import Session

from adaptive_academy.db import engine
from adaptive_academy.llm.anchor_types import AnchorClient
from adaptive_academy.llm.anthropic_anchor import AnthropicAnchorClient
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
from adaptive_academy.llm.researcher_types import ResearcherClient
from adaptive_academy.llm.types import LLMClient


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def get_llm() -> LLMClient:
    return AnthropicLLMClient(role="reasoning")


def get_researcher() -> ResearcherClient:
    return AnthropicResearcherClient(role="reasoning")


def get_anchor_client() -> AnchorClient:
    return AnthropicAnchorClient(role="reasoning")
