import logging
import os
from collections.abc import Iterator

from sqlmodel import Session

from adaptive_academy.db import engine, ensure_fts
from adaptive_academy.llm.anchor_types import AnchorClient
from adaptive_academy.llm.anthropic_anchor import AnthropicAnchorClient
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
from adaptive_academy.llm.researcher_types import ResearcherClient
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.settings import settings

logger = logging.getLogger(__name__)
_logged_retriever_degradations: set[str] = set()
_fts_available: bool | None = None


def use_agent_sdk() -> bool:
    """Opt in to the Claude Agent SDK backend (subscription auth) via env flag.

    Default is the API-key client, so nothing changes unless you set this.
    """
    return os.getenv("AA_LLM_BACKEND", "").lower() == "agent_sdk"


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def get_llm() -> LLMClient:
    if use_agent_sdk():
        from adaptive_academy.llm.agent_sdk_client import AgentSDKLLMClient
        return AgentSDKLLMClient(role="reasoning")
    return AnthropicLLMClient(role="reasoning")


def get_researcher() -> ResearcherClient:
    # In agent_sdk mode, fan out via the SDK's WebSearch tool on the subscription.
    if use_agent_sdk():
        from adaptive_academy.llm.agent_sdk_researcher import AgentSDKResearcherClient
        return AgentSDKResearcherClient(role="reasoning")
    return AnthropicResearcherClient(role="reasoning")


def get_anchor_client() -> AnchorClient:
    # Anchor generation is a no-tools structured call, so it can run on the subscription
    # by injecting the Agent SDK client into the (transport-agnostic) anchor client.
    if use_agent_sdk():
        from adaptive_academy.llm.agent_sdk_client import AgentSDKLLMClient
        return AnthropicAnchorClient(llm=AgentSDKLLMClient(role="reasoning"))
    return AnthropicAnchorClient(role="reasoning")


def get_retriever() -> Retriever:
    """Resolve the configured local retriever with safe staged fallbacks."""
    from adaptive_academy.llm.fts_retriever import FtsRetriever
    from adaptive_academy.llm.scripted_retriever import ScriptedRetriever

    configured = settings.retriever.strip().lower()
    if configured == "scripted":
        return ScriptedRetriever()
    if configured == "vec":
        configured = "hybrid"
    if configured not in {"fts", "hybrid"}:
        _warn_retriever_degradation_once(
            f"unsupported:{configured}",
            f"Unsupported retriever {settings.retriever!r}; using FTS5.",
        )
        configured = "fts"
    if configured == "hybrid":
        _warn_retriever_degradation_once(
            "hybrid",
            "Hybrid retrieval is not available yet; using FTS5.",
        )
    global _fts_available
    if _fts_available is None:
        _fts_available = ensure_fts(engine)
    if _fts_available:
        return FtsRetriever()
    _warn_retriever_degradation_once(
        "fts",
        "FTS5 is unavailable; using scripted token-overlap retrieval.",
    )
    return ScriptedRetriever()


def reset_retriever_cache() -> None:
    """Clear the cached FTS5 availability result."""
    global _fts_available
    _fts_available = None


def _warn_retriever_degradation_once(key: str, message: str) -> None:
    if key in _logged_retriever_degradations:
        return
    _logged_retriever_degradations.add(key)
    logger.warning(message)
