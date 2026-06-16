from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class AnchorBrief:
    """One fan-out unit: generate anchors grounded in a single accepted source."""

    source_doc_id: int
    title: str
    summary: str
    url: str
    key_concepts: list[str] = field(default_factory=list)


@dataclass
class RawAnchor:
    """A candidate anchor returned by a subagent (pre-dedup, pre-persist)."""

    question: str
    reference_answer: str = ""
    key_points: list[str] = field(default_factory=list)
    concept_name: str = ""  # linked to a Concept by name by the orchestrator


class AnchorClient(Protocol):
    """A single fan-out subagent: generates anchors for one source brief."""

    def generate(self, brief: AnchorBrief) -> list[RawAnchor]: ...
