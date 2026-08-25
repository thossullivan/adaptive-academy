"""Protocol shared by local text embedding backends."""

from typing import Protocol


class Embedder(Protocol):
    """Embed text locally for vector retrieval and duplicate detection."""

    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
