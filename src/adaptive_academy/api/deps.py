import logging
from collections.abc import Callable, Iterator

from sqlmodel import Session

from adaptive_academy.db import engine, ensure_fts, ensure_vec
from adaptive_academy.engine.fetch import fetch_artifact_text
from adaptive_academy.engine.solution_guard import GUARD_MAX_TOKENS
from adaptive_academy.llm.anchor_types import AnchorClient
from adaptive_academy.llm.anthropic_anchor import AnthropicAnchorClient
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
from adaptive_academy.llm.backends import use_agent_sdk as _use_agent_sdk
from adaptive_academy.llm.embedder_types import Embedder
from adaptive_academy.llm.researcher_types import ResearcherClient
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.settings import settings

logger = logging.getLogger(__name__)
_logged_retriever_degradations: set[str] = set()
_fts_available: bool | None = None
_vec_available: bool | None = None
_hybrid_available: bool | None = None
_embedder: Embedder | None = None


def use_agent_sdk() -> bool:
    """Opt in to the Claude Agent SDK backend (subscription auth) via env flag.

    Default is the API-key client, so nothing changes unless you set this. The other choice,
    AA_LLM_BACKEND=openrouter, keeps the API-key clients below and points them at OpenRouter
    (llm/backends.py), so it needs no branch here.
    """
    return _use_agent_sdk()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def get_llm() -> LLMClient:
    if use_agent_sdk():
        from adaptive_academy.llm.agent_sdk_client import AgentSDKLLMClient
        return AgentSDKLLMClient(role="reasoning")
    return AnthropicLLMClient(role="reasoning")


def get_guard_llm() -> LLMClient:
    """The tutor's solution guard (engine/solution_guard.py): a cheap structured check on
    the copy role (Haiku by default), on whichever backend the tutor itself uses."""
    if use_agent_sdk():
        from adaptive_academy.llm.agent_sdk_client import AgentSDKLLMClient
        return AgentSDKLLMClient(role="copy")
    return AnthropicLLMClient(role="copy", max_tokens=GUARD_MAX_TOKENS)


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


def get_fetcher() -> Callable[[str], str | None]:
    """Return the SSRF-guarded source-document text fetcher."""
    return fetch_artifact_text


def get_embedder() -> Embedder:
    """Resolve the deterministic test embedder or the local ONNX embedder."""
    global _embedder
    if _embedder is not None:
        return _embedder
    if settings.retriever.strip().lower() == "scripted":
        from adaptive_academy.llm.scripted_embedder import ScriptedEmbedder

        _embedder = ScriptedEmbedder()
        return _embedder

    from adaptive_academy.llm.onnx_embedder import OnnxEmbedder

    _embedder = OnnxEmbedder()
    return _embedder


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
    global _fts_available
    if _fts_available is None:
        _fts_available = ensure_fts(engine)
    if not _fts_available:
        _warn_retriever_degradation_once(
            "fts",
            "FTS5 is unavailable; using scripted token-overlap retrieval.",
        )
        return ScriptedRetriever()

    fts = FtsRetriever()
    if configured == "fts":
        return fts

    global _hybrid_available, _vec_available
    if _vec_available is None:
        _vec_available = ensure_vec(engine)
    if _vec_available and _hybrid_available is not False:
        try:
            embedder = get_embedder()
            from adaptive_academy.llm.hybrid_retriever import HybridRetriever

            if _hybrid_available is None:
                embedder.embed(["warm-up"])
            retriever = HybridRetriever(fts, embedder)
            _hybrid_available = True
            return retriever
        except Exception:
            _hybrid_available = False

    _warn_retriever_degradation_once(
        "hybrid",
        "Hybrid retrieval is unavailable; using FTS5.",
    )
    return fts


def reset_retriever_cache() -> None:
    """Clear the cached FTS5 and sqlite-vec availability results."""
    global _embedder, _fts_available, _hybrid_available, _vec_available
    _embedder = None
    _fts_available = None
    _hybrid_available = None
    _vec_available = None


def _warn_retriever_degradation_once(key: str, message: str) -> None:
    if key in _logged_retriever_degradations:
        return
    _logged_retriever_degradations.add(key)
    logger.warning(message)
