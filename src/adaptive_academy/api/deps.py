from collections.abc import Iterator

from sqlmodel import Session

from adaptive_academy.db import engine
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.types import LLMClient


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def get_llm() -> LLMClient:
    return AnthropicLLMClient(role="reasoning")
