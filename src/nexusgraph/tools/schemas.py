"""Typed tool arguments (validated at the boundary)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from nexusgraph.domain.models import QuerySpec


class SearchDocumentsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=8_000)
    k: int = Field(default=6, ge=1, le=25)
    document_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    content_types: list[str] = Field(default_factory=list)


class RunSparqlArgs(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    include_named_graphs: bool = False


class QueryStructuredArgs(BaseModel):
    spec: QuerySpec


class GetEntityArgs(BaseModel):
    entity_id: str = Field(min_length=3, max_length=128)


class GetRelationshipsArgs(BaseModel):
    entity_id: str = Field(min_length=3, max_length=128)
    relation: str | None = Field(default=None, max_length=64)


class RetrieveDocumentArgs(BaseModel):
    document_id: str = Field(min_length=3, max_length=128)


class VerifyClaimArgs(BaseModel):
    claim: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
