"""Hybrid retrieval: dense vector search + BM25 lexical rerank."""

from __future__ import annotations

from nexusgraph.config import LimitsSettings
from nexusgraph.domain.models import SearchHit
from nexusgraph.observability.logging import get_logger
from nexusgraph.retrieval.bm25 import bm25_scores
from nexusgraph.retrieval.embeddings import Embedder
from nexusgraph.store.documents import DocumentStore
from nexusgraph.store.vector import ChunkFilter, VectorIndex

logger = get_logger("retrieval")

DENSE_WEIGHT = 0.65
LEXICAL_WEIGHT = 0.35


class RetrievalService:
    def __init__(self, document_store: DocumentStore, vector_index: VectorIndex,
                 embedder: Embedder, limits: LimitsSettings) -> None:
        self._documents = document_store
        self._index = vector_index
        self._embedder = embedder
        self._limits = limits

    def search(
        self,
        query: str,
        *,
        k: int | None = None,
        document_ids: list[str] | None = None,
        entity_ids: list[str] | None = None,
        content_types: list[str] | None = None,
    ) -> list[SearchHit]:
        k = k or self._limits.retrieval_k
        filters = ChunkFilter(
            document_ids=tuple(document_ids or ()),
            content_types=tuple(content_types or ()),
            entity_ids=tuple(entity_ids or ()),
        )
        embedding = self._embedder.embed_texts([query])[0]
        candidates = self._index.search(embedding, k * 4, filters)
        if not candidates:
            return []

        chunks = self._documents.get_chunks([c.chunk_id for c in candidates])
        chunk_by_id = {c.id: c for c in chunks}
        ordered = [chunk_by_id[c.chunk_id] for c in candidates if c.chunk_id in chunk_by_id]
        dense_by_id = {c.chunk_id: c.dense_score for c in candidates}

        lexical = bm25_scores(query, [c.text for c in ordered])

        hits: list[SearchHit] = []
        for chunk, lex in zip(ordered, lexical, strict=True):
            dense = dense_by_id.get(chunk.id, 0.0)
            score = DENSE_WEIGHT * dense + LEXICAL_WEIGHT * lex
            hits.append(SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                score=round(score, 4),
                text=chunk.text,
                entity_ids=chunk.entity_ids,
                dense_score=round(dense, 4),
                lexical_score=round(lex, 4),
            ))
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[:k]
        titles = {d.id: d.title for d in self._documents.list_documents(limit=10_000)}
        for hit in hits:
            hit.document_title = titles.get(hit.document_id)
        # Bound total returned characters (THREAT_MODEL: max retrieval size).
        budget = self._limits.max_retrieval_chars
        kept: list[SearchHit] = []
        for hit in hits:
            if budget - len(hit.text) < 0 and kept:
                break
            budget -= len(hit.text)
            kept.append(hit)
        logger.info("retrieval ok", extra={"tool": "search_documents", "k": len(kept)})
        return kept
