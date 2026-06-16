from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SearchBrief:
    """One fan-out angle: a sub-question the Researcher searches the web for."""

    angle: str  # stable key, e.g. "foundational_papers"
    query: str  # the web-search query / instruction


@dataclass
class RawSource:
    """A candidate source returned by a subagent (pre-dedup, pre-rank)."""

    title: str
    url: str
    tier: int = 3  # 1 | 2 | 3
    summary: str = ""
    why: str = ""
    relevance: float = 0.0  # 0..1
    angle: str = ""  # stamped by the orchestrator from the brief


class ResearcherClient(Protocol):
    """A single fan-out subagent: searches the web for one brief, returns sources."""

    def search(self, brief: SearchBrief) -> list[RawSource]: ...
