"""Dense and sparse retrieval, reciprocal rank fusion, and late interaction."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Literal

from nexusgraph.config import LimitsSettings
from nexusgraph.domain.models import Chunk, SearchHit
from nexusgraph.retrieval.bm25 import bm25_scores
from nexusgraph.retrieval.context import PackedContext, interaction, pack_context
from nexusgraph.retrieval.embeddings import Embedder
from nexusgraph.store.documents import DocumentStore
from nexusgraph.store.vector import ChunkFilter, VectorIndex

RetrievalMode = Literal["dense", "rrf", "rerank"]
RRF_K = 60


def reciprocal_rank_fusion(*rankings: Iterable[str]) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, 1):
            scores[chunk_id] += 1 / (RRF_K + rank)
    return dict(scores)


def _contextual_text(chunk: Chunk) -> str:
    headings = chunk.metadata.get("headings")
    return f"{' > '.join(headings)}\n\n{chunk.text}" if headings else chunk.text


class RetrievalService:
    def __init__(
        self,
        document_store: DocumentStore,
        vector_index: VectorIndex,
        embedder: Embedder,
        limits: LimitsSettings,
    ) -> None:
        self._documents = document_store
        self._index = vector_index
        self._embedder = embedder
        self._limits = limits

    def rank(
        self,
        query: str,
        *,
        depth: int,
        filters: ChunkFilter | None = None,
        mode: RetrievalMode = "rerank",
    ) -> list[SearchHit]:
        """Return ranked candidates before evidence and context-budget filtering."""
        if depth <= 0 or not query.strip():
            return []
        filters = filters or ChunkFilter()
        embedding = self._embedder.embed_texts([query])[0]
        dense = self._index.search(embedding, depth, filters)
        dense_scores = {candidate.chunk_id: candidate.dense_score for candidate in dense}
        lexical_scores: dict[str, float] = {}
        if mode == "dense":
            chunks = self._documents.get_chunks(list(dense_scores))
            scores = dense_scores
        else:
            chunks = self._documents.matching_chunks(filters)
            lexical = bm25_scores(query, [_contextual_text(chunk) for chunk in chunks])
            lexical_scores = {
                chunk.id: score for chunk, score in zip(chunks, lexical, strict=True) if score > 0
            }
            sparse_ids = sorted(lexical_scores, key=lambda cid: (-lexical_scores[cid], cid))
            scores = reciprocal_rank_fusion(dense_scores, sparse_ids[:depth])

        hits: list[SearchHit] = []
        for chunk in chunks:
            if chunk.id not in scores:
                continue
            text = _contextual_text(chunk)
            similarity, coverage = interaction(query, text)
            hits.append(
                SearchHit(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    score=scores[chunk.id],
                    text=text,
                    entity_ids=chunk.entity_ids,
                    dense_score=dense_scores.get(chunk.id),
                    lexical_score=lexical_scores.get(chunk.id),
                    reranker_score=similarity if mode == "rerank" else None,
                    evidence_coverage=coverage,
                    citation=chunk.metadata.get("provenance", {}).get("location")
                    if "start_line" in chunk.metadata
                    else None,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.chunk_id))
        hits = hits[:depth]
        if mode == "rerank":
            hits.sort(key=lambda hit: (-(hit.reranker_score or 0.0), -hit.score, hit.chunk_id))
        return hits

    def pack(self, hits: list[SearchHit], *, k: int) -> PackedContext:
        return pack_context(
            hits,
            k=k,
            token_budget=self._limits.max_context_tokens,
            char_budget=self._limits.max_retrieval_chars,
            min_coverage=self._limits.min_evidence_coverage,
        )

    def search(
        self,
        query: str,
        *,
        k: int | None = None,
        document_ids: list[str] | None = None,
        entity_ids: list[str] | None = None,
        content_types: list[str] | None = None,
    ) -> list[SearchHit]:
        k = self._limits.retrieval_k if k is None else k
        filters = ChunkFilter(
            document_ids=tuple(document_ids or ()),
            content_types=tuple(content_types or ()),
            entity_ids=tuple(entity_ids or ()),
        )
        packed = self.pack(self.rank(query, depth=max(40, k * 4), filters=filters), k=k)
        titles = {doc.id: doc.title for doc in self._documents.list_documents(limit=10_000)}
        return [
            hit.model_copy(update={"document_title": titles.get(hit.document_id)})
            for hit in packed.hits
        ]
