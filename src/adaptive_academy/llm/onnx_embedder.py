"""FastEmbed-backed local ONNX text embeddings."""

import inspect
import os
import tempfile
from pathlib import Path
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
        self.allow_download = settings.embedding_allow_download
        if not self.allow_download and not _model_is_cached(
            self.name,
            self.cache_dir,
        ):
            raise RuntimeError("embedding model not cached; downloads disabled")
        self._model: Any | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._model is None:
            kwargs: dict[str, Any] = {
                "model_name": self.name,
                "cache_dir": self.cache_dir,
                "lazy_load": True,
            }
            parameters = inspect.signature(TextEmbedding.__init__).parameters
            if not self.allow_download and "local_files_only" in parameters:
                kwargs["local_files_only"] = True
            self._model = TextEmbedding(**kwargs)
        vectors = [vector.tolist() for vector in self._model.embed(texts)]
        if any(len(vector) != self.dim for vector in vectors):
            raise ValueError(f"embedding model must return {self.dim} dimensions")
        return vectors


def _model_is_cached(model_name: str, cache_dir: str | None) -> bool:
    """Recognize FastEmbed's Hugging Face and legacy model directories."""
    if cache_dir:
        root = Path(cache_dir).expanduser()
    else:
        default = Path(tempfile.gettempdir()) / "fastembed_cache"
        root = Path(os.getenv("FASTEMBED_CACHE_PATH", str(default))).expanduser()
    if not root.is_dir():
        return False

    repo_name = model_name.replace("/", "--").casefold()
    model_slug = model_name.rsplit("/", 1)[-1].casefold()
    expected_hf_name = f"models--{repo_name}"
    candidates = [root, *root.rglob("*")]
    return any(
        candidate.is_dir()
        and (
            candidate.name.casefold() == expected_hf_name
            or model_slug in candidate.name.casefold()
        )
        and any(candidate.rglob("*.onnx"))
        for candidate in candidates
    )
