"""ORM models for entities, relationships, documents, chunks and traces.

Structured quantitative domain tables (trials, metrics, ...) are created from
the declarative schema in ``store.structured`` rather than ORM classes: the
schema dict doubles as the SQL tool's table/column allowlist.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")
_EMBEDDING_VARIANT = JSON().with_variant(Vector(), "postgresql")


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EntityRow(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    attributes: Mapped[dict] = mapped_column(_JSON_VARIANT, default=dict)
    source_ids: Mapped[list] = mapped_column(_JSON_VARIANT, default=list)


class RelationshipRow(Base):
    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(128))
    target_id: Mapped[str] = mapped_column(String(128))
    relation: Mapped[str] = mapped_column(String(64))
    properties: Mapped[dict] = mapped_column(_JSON_VARIANT, default=dict)
    source_ids: Mapped[list] = mapped_column(_JSON_VARIANT, default=list)


Index("ix_rel_source", RelationshipRow.source_id, RelationshipRow.relation)
Index("ix_rel_target", RelationshipRow.target_id, RelationshipRow.relation)


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(64), index=True)
    source_path: Mapped[str] = mapped_column(String(1024))
    text: Mapped[str] = mapped_column(Text, default="")
    doc_metadata: Mapped[dict] = mapped_column("metadata", _JSON_VARIANT, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChunkRow(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(128), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    entity_ids: Mapped[list] = mapped_column(_JSON_VARIANT, default=list)
    chunk_metadata: Mapped[dict] = mapped_column("metadata", _JSON_VARIANT, default=dict)
    embedding: Mapped[list | None] = mapped_column(_EMBEDDING_VARIANT, nullable=True)


class TraceRow(Base):
    __tablename__ = "traces"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 index=True)
    question: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(16), default="running")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    duration_ms: Mapped[float | None] = mapped_column(Float, default=None)
    spans: Mapped[list] = mapped_column(_JSON_VARIANT, default=list)
    attributes: Mapped[dict] = mapped_column(_JSON_VARIANT, default=dict)
    usage: Mapped[dict] = mapped_column(_JSON_VARIANT, default=dict)
