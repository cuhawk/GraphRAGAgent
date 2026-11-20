"""SQL-backed document + chunk store."""

from __future__ import annotations

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, defer

from nexusgraph.db.orm import ChunkRow, DocumentRow
from nexusgraph.domain.models import Chunk, DocumentMeta
from nexusgraph.store.vector import ChunkFilter


class DocumentStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------- documents
    def upsert_document(self, meta: DocumentMeta) -> None:
        with Session(self._engine) as session:
            row = session.get(DocumentRow, meta.id)
            if row is None:
                row = DocumentRow(id=meta.id)
                session.add(row)
            row.title = meta.title
            row.content_type = meta.content_type
            row.source_path = meta.source_path
            row.text = meta.text
            row.doc_metadata = meta.metadata
            session.commit()

    def get_document(self, document_id: str) -> DocumentMeta | None:
        with Session(self._engine) as session:
            row = session.get(DocumentRow, document_id)
            if row is None:
                return None
            return DocumentMeta(
                id=row.id,
                title=row.title,
                content_type=row.content_type,
                source_path=row.source_path,
                text=row.text,
                metadata=row.doc_metadata,
            )

    def list_documents(self, limit: int = 100, offset: int = 0) -> list[DocumentMeta]:
        with Session(self._engine) as session:
            rows = (
                session.execute(
                    select(DocumentRow).order_by(DocumentRow.id).limit(limit).offset(offset)
                )
                .scalars()
                .all()
            )
            return [
                DocumentMeta(
                    id=r.id,
                    title=r.title,
                    content_type=r.content_type,
                    source_path=r.source_path,
                    text="",
                    metadata=r.doc_metadata,
                )
                for r in rows
            ]

    def delete_document(self, document_id: str) -> None:
        with Session(self._engine) as session:
            session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
            session.execute(delete(DocumentRow).where(DocumentRow.id == document_id))
            session.commit()

    # ---------------------------------------------------------------- chunks
    def replace_chunks(self, document_id: str, chunks: list[Chunk]) -> None:
        with Session(self._engine) as session:
            session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
            for chunk in chunks:
                session.add(
                    ChunkRow(
                        id=chunk.id,
                        document_id=document_id,
                        ordinal=chunk.ordinal,
                        text=chunk.text,
                        entity_ids=chunk.entity_ids,
                        chunk_metadata=chunk.metadata,
                        embedding=chunk.embedding,
                    )
                )
            session.commit()

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        with Session(self._engine) as session:
            row = session.get(ChunkRow, chunk_id)
            return self._chunk_from_row(row) if row else None

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        with Session(self._engine) as session:
            rows = (
                session.execute(select(ChunkRow).where(ChunkRow.id.in_(chunk_ids))).scalars().all()
            )
        by_id = {r.id: self._chunk_from_row(r) for r in rows}
        return [by_id[cid] for cid in chunk_ids if cid in by_id]

    def chunks_for_document(self, document_id: str) -> list[Chunk]:
        with Session(self._engine) as session:
            rows = (
                session.execute(
                    select(ChunkRow)
                    .where(ChunkRow.document_id == document_id)
                    .order_by(ChunkRow.ordinal)
                )
                .scalars()
                .all()
            )
        return [self._chunk_from_row(r) for r in rows]

    def matching_chunks(self, filters: ChunkFilter) -> list[Chunk]:
        """Read the sparse corpus without loading embeddings."""
        query = (
            select(ChunkRow)
            .join(DocumentRow, ChunkRow.document_id == DocumentRow.id)
            .options(defer(ChunkRow.embedding))
            .order_by(ChunkRow.id)
        )
        if filters.document_ids:
            query = query.where(ChunkRow.document_id.in_(filters.document_ids))
        if filters.content_types:
            query = query.where(DocumentRow.content_type.in_(filters.content_types))
        entity_ids = set(filters.entity_ids)
        with Session(self._engine) as session:
            return [
                self._chunk_from_row(row, include_embedding=False)
                for row in session.scalars(query)
                if not entity_ids or entity_ids.intersection(row.entity_ids or ())
            ]

    def chunk_count(self) -> int:
        with Session(self._engine) as session:
            return int(session.scalar(select(func.count()).select_from(ChunkRow)) or 0)

    def document_count(self) -> int:
        with Session(self._engine) as session:
            return int(session.scalar(select(func.count()).select_from(DocumentRow)) or 0)

    @staticmethod
    def _chunk_from_row(row: ChunkRow, *, include_embedding: bool = True) -> Chunk:
        return Chunk(
            id=row.id,
            document_id=row.document_id,
            ordinal=row.ordinal,
            text=row.text,
            entity_ids=row.entity_ids or [],
            metadata=row.chunk_metadata or {},
            embedding=list(row.embedding)
            if include_embedding and row.embedding is not None
            else None,
        )
