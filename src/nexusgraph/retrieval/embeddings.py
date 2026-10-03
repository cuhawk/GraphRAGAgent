"""Embedding backends.

Default: :class:`HashEmbedder` — deterministic feature-hashing embeddings
(word tokens + char trigrams, signed buckets, L2-normalised). Zero network,
zero cost, fully reproducible; the standard caveat (no deep semantics) is
documented. Configure ``NEXUSGRAPH_LLM__EMBEDDING_PROVIDER=openai-compatible``
for real embeddings via any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

from nexusgraph.config import LLMSettings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...
    @property
    def dim(self) -> int: ...


class HashEmbedder:
    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        words = _TOKEN_RE.findall(text.lower())
        features: list[str] = []
        for word in words:
            features.append(word)
            if len(word) > 3:
                padded = f"^{word}$"
                features.extend(padded[i : i + 3] for i in range(len(padded) - 2))
        for feature in features[:4_000]:  # bounded work per document
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class OpenAICompatEmbedder:
    def __init__(self, settings: LLMSettings) -> None:
        if not settings.base_url:
            raise ValueError("openai-compatible embedding provider requires a base_url")
        self._base_url = settings.base_url.rstrip("/")
        self._model = settings.embedding_model
        self._api_key = settings.api_key
        self._dim = settings.embedding_dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = httpx.post(
            f"{self._base_url}/embeddings",
            json={"model": self._model, "input": list(texts)},
            headers=headers,
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload["data"], key=lambda item: item["index"])
        embeddings = [item["embedding"] for item in data]
        if embeddings and len(embeddings[0]) != self._dim:
            raise ValueError(
                f"embedding dimension mismatch: endpoint returned "
                f"{len(embeddings[0])}, configured {self._dim}"
            )
        return embeddings


def make_embedder(settings: LLMSettings) -> Embedder:
    if settings.embedding_provider == "openai-compatible":
        return OpenAICompatEmbedder(settings)
    return HashEmbedder(dim=settings.embedding_dim)
