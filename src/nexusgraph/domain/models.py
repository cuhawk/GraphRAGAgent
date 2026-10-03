"""Core domain models shared by stores, tools, agent and API.

Everything a tool returns is a Pydantic model: tool contracts are type-checked
at the boundary and every result carries the fields needed to derive
:class:`Evidence` (source_id / source_type / location) — the backbone of the
citation system.
"""

from __future__ import annotations

import enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Provenance / citations
# --------------------------------------------------------------------------- #


class SourceType(enum.StrEnum):
    document = "document"
    sql = "sql"
    rdf = "rdf"


class Evidence(BaseModel):
    """A machine-checkable reference to the underlying data a claim rests on."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str  # ledger-assigned, e.g. "ev-0001"
    source_id: str  # document id, table name + row key, or RDF subject
    source_type: SourceType
    location: str  # chunk id / row key / binding summary
    snippet: str | None = None
    confidence: float = 1.0
    uri: str | None = None  # RDF subject URI when source_type=rdf


class Claim(BaseModel):
    claim: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None
    unsupported: bool = False  # verifier flags claims lacking real evidence


# --------------------------------------------------------------------------- #
# Knowledge graph entities / relationships / documents
# --------------------------------------------------------------------------- #


class Entity(BaseModel):
    id: str  # "<type>:<local_id>", e.g. "trial:T-1001"
    type: str
    name: str
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)  # provenance


class Relationship(BaseModel):
    source_id: str  # entity id
    target_id: str
    relation: str  # e.g. TRIAL_HAS_SITE
    properties: dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)


class DocumentMeta(BaseModel):
    id: str
    title: str
    content_type: str  # text/markdown/csv/json/pdf
    source_path: str
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    id: str  # "<document_id>#chunk-0007"
    document_id: str
    ordinal: int
    text: str
    entity_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    score: float
    text: str
    document_title: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    dense_score: float | None = None
    lexical_score: float | None = None


# --------------------------------------------------------------------------- #
# Tool results
# --------------------------------------------------------------------------- #


class SparqlResult(BaseModel):
    query: str
    variables: list[str]
    rows: list[dict[str, str]]
    row_count: int
    truncated: bool = False


class Aggregation(BaseModel):
    func: Literal["sum", "avg", "min", "max", "count"]
    column: str | None = None  # None allowed only for count(*)


class FilterCondition(BaseModel):
    column: str
    op: Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "like"]
    value: Any


class OrderBy(BaseModel):
    column: str
    direction: Literal["asc", "desc"] = "asc"


class QuerySpec(BaseModel):
    """Typed structured-query request compiled to SQL — the model never writes raw SQL."""

    table: str
    select: list[str] = Field(default_factory=list)
    filters: list[FilterCondition] = Field(default_factory=list)
    aggregations: list[Aggregation] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: int = Field(default=200, ge=1, le=500)


class StructuredQueryResult(BaseModel):
    executed_sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False


class EntityDetail(BaseModel):
    entity: Entity
    relationships: list[Relationship] = Field(default_factory=list)


class DocumentDetail(BaseModel):
    document: DocumentMeta
    chunk_count: int = 0


class ClaimVerification(BaseModel):
    supported: bool
    verdict: str
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Planning / orchestration
# --------------------------------------------------------------------------- #

ToolName = Literal[
    "search_documents",
    "run_sparql",
    "query_structured_data",
    "get_entity",
    "get_relationships",
    "retrieve_document",
    "verify_claim",
]

QuestionType = Literal[
    "semantic",
    "relationship",
    "quantitative",
    "mixed",
    "entity_lookup",
    "unanswerable",
]


class PlanStep(BaseModel):
    tool: ToolName
    rationale: str
    args: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    question_type: QuestionType
    steps: list[PlanStep]
    rationale: str = ""


class ToolRun(BaseModel):
    tool: ToolName
    args: dict[str, Any]
    status: Literal["ok", "error", "empty"]
    error: str | None = None
    duration_ms: float = 0.0
    result_count: int = 0


# --------------------------------------------------------------------------- #
# LLM usage accounting
# --------------------------------------------------------------------------- #


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    estimated_cost_usd: float = 0.0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.llm_calls += other.llm_calls
        self.estimated_cost_usd = round(self.estimated_cost_usd + other.estimated_cost_usd, 6)


# --------------------------------------------------------------------------- #
# Final grounded answer
# --------------------------------------------------------------------------- #


class AgentAnswer(BaseModel):
    question: str
    answer: str  # may contain [1]-style citation markers pointing into `evidence`
    question_type: QuestionType
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    tools_used: list[ToolRun] = Field(default_factory=list)
    plan_rationale: str = ""
    trace_id: str
    insufficient: bool = False  # True => agent explicitly said it cannot answer
    insufficient_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    latency_ms: float = 0.0
