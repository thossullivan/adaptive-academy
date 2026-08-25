"""FastEmbed-backed local ONNX text embeddings."""

from typing import Any

from adaptive_academy.engine.memory import VECTOR_DIM
from adaptive_academy.settings import settings

try:
    from fastembed import TextEmbedding
except ImportError:
    TextEmbedding = None  # type: ignore[assignment,misc]


class OnnxEmbedder:
    """Load the configured FastEmbed model only when text is first embedded."""

    dim = VECTOR_DIM

    def __init__(self, model: str | None = None):
        if TextEmbedding is None:
            raise ImportError("fastembed is required for ONNX embeddings")
        self.name = model or settings.embedding_model
        self.cache_dir = settings.embedding_cache_dir or None
        self._model: Any | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._model is None:
            self._model = TextEmbedding(
                model_name=self.name,
                cache_dir=self.cache_dir,
                lazy_load=True,
            )
        vectors = [vector.tolist() for vector in self._model.embed(texts)]
        if any(len(vector) != self.dim for vector in vectors):
            raise ValueError(f"embedding model must return {self.dim} dimensions")
        return vectors
