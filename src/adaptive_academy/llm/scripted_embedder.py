"""Deterministic local embedder for tests."""

import hashlib
import math
import re

from adaptive_academy.engine.memory import VECTOR_DIM

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class ScriptedEmbedder:
    """Create stable, L2-normalized hashed bag-of-words vectors."""

    name = "scripted"

    def __init__(self, dim: int = VECTOR_DIM):
        if dim <= 0:
            raise ValueError("embedding dimension must be positive")
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _TOKEN_RE.findall(text.casefold()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "little") % self.dim
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[bucket] += sign

        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0.0:
            return vector
        return [value / magnitude for value in vector]
