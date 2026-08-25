"""Protocol shared by local memory retrieval backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from sqlmodel import Session

from adaptive_academy.models import Chunk

if TYPE_CHECKING:
    from adaptive_academy.engine.memory import ChunkFilter


@dataclass(frozen=True)
class Hit:
    """One retrieved chunk and its query-relative score."""

    chunk: Chunk
    score: float
    via: Literal["direct", "link"] = "direct"


class Retriever(Protocol):
    """Rank indexed chunks while keeping storage details behind one seam."""

    name: str

    def search(
        self,
        session: Session,
        query: str,
        *,
        where: ChunkFilter,
        k: int,
    ) -> list[tuple[int, float]]: ...

    def on_index(self, session: Session, chunk_ids: list[int]) -> None: ...
