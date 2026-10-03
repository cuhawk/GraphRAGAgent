"""Vector index over chunk embeddings.

Two implementations behind one protocol:

- :class:`LocalVectorIndex` — numpy cosine over embeddings loaded from the
  chunks table (JSON column on SQLite); used by the ``local`` profile.
- :class:`PgVectorIndex` — pgvector cosine distance search; used by the
  ``postgres`` profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from sqlalchemy import Engine, select, text

from nexusgraph.observability.logging import get_logger

logger = get_logger("store.vector")


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: str
    dense_score: float


@dataclass(frozen=True)
class ChunkFilter:
    document_ids: tuple[str, ...] = ()
    content_types: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()


class VectorIndex(Protocol):
    def search(
        self,
        embedding: list[float],
        k: int,
        filters: ChunkFilter | None = None,
    ) -> list[ScoredChunk]: ...
    def refresh(self) -> int: ...
    def count(self) -> int: ...


class LocalVectorIndex:
    """In-process numpy index; refreshed from the chunks table on demand."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._ids: list[str] = []
        self._matrix: np.ndarray | None = None
        self._meta: dict[str, tuple[str, list[str], str]] = {}  # id -> (doc_id, eids, ctype)
        self.refresh()

    def refresh(self) -> int:
        from nexusgraph.db.orm import ChunkRow, DocumentRow

        with self._engine.connect() as conn:
            rows = conn.execute(
                select(
                    ChunkRow.id,
                    ChunkRow.document_id,
                    ChunkRow.entity_ids,
                    ChunkRow.embedding,
                    DocumentRow.content_type,
                )
                .join(DocumentRow, ChunkRow.document_id == DocumentRow.id)
                .where(ChunkRow.embedding.is_not(None))
            ).all()
        ids: list[str] = []
        vectors: list[list[float]] = []
        meta: dict[str, tuple[str, list[str], str]] = {}
        for chunk_id, document_id, entity_ids, embedding, content_type in rows:
            ids.append(chunk_id)
            vectors.append([float(x) for x in (embedding or [])])
            meta[chunk_id] = (document_id, entity_ids or [], content_type)
        self._ids = ids
        self._meta = meta
        self._matrix = np.array(vectors, dtype=np.float32) if vectors else None
        logger.info("local vector index refreshed: %d vectors", len(ids))
        return len(ids)

    def count(self) -> int:
        return 0 if self._matrix is None else int(self._matrix.shape[0])

    def search(
        self,
        embedding: list[float],
        k: int,
        filters: ChunkFilter | None = None,
    ) -> list[ScoredChunk]:
        if self._matrix is None or not self._ids:
            return []
        query = np.array(embedding, dtype=np.float32)
        qnorm = np.linalg.norm(query)
        if qnorm == 0:
            return []
        query = query / qnorm
        norms = np.linalg.norm(self._matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        sims = (self._matrix / norms) @ query  # cosine similarity in [-1, 1]
        sims = (sims + 1.0) / 2.0  # -> [0, 1]

        order = np.argsort(-sims)
        results: list[ScoredChunk] = []
        for idx in order:
            chunk_id = self._ids[int(idx)]
            if filters and not self._passes(chunk_id, filters):
                continue
            results.append(ScoredChunk(chunk_id=chunk_id, dense_score=float(sims[idx])))
            if len(results) >= k:
                break
        return results

    def _passes(self, chunk_id: str, filters: ChunkFilter) -> bool:
        document_id, entity_ids, content_type = self._meta.get(chunk_id, ("", [], ""))
        if filters.document_ids and document_id not in filters.document_ids:
            return False
        if filters.content_types and content_type not in filters.content_types:
            return False
        return not (filters.entity_ids and not (set(entity_ids) & set(filters.entity_ids)))


class PgVectorIndex:
    """pgvector-backed index (cosine distance)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def refresh(self) -> int:  # pgvector queries the table directly
        return self.count()

    def count(self) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")
            ).scalar()
            return int(row or 0)

    def search(
        self,
        embedding: list[float],
        k: int,
        filters: ChunkFilter | None = None,
    ) -> list[ScoredChunk]:
        vector_literal = "[" + ",".join(f"{x:.7g}" for x in embedding) + "]"
        sql = (
            "SELECT chunks.id, 1 - (chunks.embedding <=> :vec) AS score "
            "FROM chunks JOIN documents ON documents.id = chunks.document_id "
            "WHERE chunks.embedding IS NOT NULL"
        )
        params: dict[str, object] = {"vec": vector_literal}
        if filters:
            if filters.document_ids:
                sql += " AND chunks.document_id = ANY(:doc_ids)"
                params["doc_ids"] = list(filters.document_ids)
            if filters.content_types:
                sql += " AND documents.content_type = ANY(:ctypes)"
                params["ctypes"] = list(filters.content_types)
            if filters.entity_ids:
                ors = " OR ".join(
                    f"chunks.entity_ids @> :ent_{i}::jsonb" for i in range(len(filters.entity_ids))
                )
                sql += f" AND ({ors})"
                for i, ent in enumerate(filters.entity_ids):
                    params[f"ent_{i}"] = f'["{ent}"]'
        sql += " ORDER BY chunks.embedding <=> :vec LIMIT :k"
        params["k"] = k
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).all()
        return [ScoredChunk(chunk_id=str(r[0]), dense_score=float(r[1])) for r in rows]


def make_vector_index(engine: Engine, profile: str) -> VectorIndex:
    return PgVectorIndex(engine) if profile == "postgres" else LocalVectorIndex(engine)
