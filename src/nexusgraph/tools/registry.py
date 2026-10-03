"""Tool registry: name -> (handler, args-model, description, result-kind).

The registry is the single source of truth for the tool contracts; the MCP
server and the agent's planner descriptions derive from it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from nexusgraph.domain.models import ToolName
from nexusgraph.tools import implementations as impl
from nexusgraph.tools.schemas import (
    GetEntityArgs,
    GetRelationshipsArgs,
    QueryStructuredArgs,
    RetrieveDocumentArgs,
    RunSparqlArgs,
    SearchDocumentsArgs,
    VerifyClaimArgs,
)


@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    description: str
    args_model: type[BaseModel]
    handler: Callable[..., Any]
    # one of: hits | sparql | structured | entity | relationships |
    # document | verification
    result_kind: str


REGISTRY: dict[ToolName, ToolSpec] = {
    "search_documents": ToolSpec(
        name="search_documents",
        description=("Hybrid semantic search over the document corpus "
                     "(dense + BM25 rerank). Use for questions about what "
                     "documents say, evidence, or free-text topics."),
        args_model=SearchDocumentsArgs,
        handler=impl.search_documents,
        result_kind="hits",
    ),
    "run_sparql": ToolSpec(
        name="run_sparql",
        description=("Run a read-only SPARQL SELECT/ASK query against the RDF "
                     "knowledge graph (companies, products, compounds, trials, "
                     "sites, investigators, milestones, safety events, "
                     "document mentions). Queries are guarded; updates and "
                     "federation are rejected."),
        args_model=RunSparqlArgs,
        handler=impl.run_sparql,
        result_kind="sparql",
    ),
    "query_structured_data": ToolSpec(
        name="query_structured_data",
        description=("Run a typed aggregate/select query (QuerySpec) over the "
                     "relational tables (trials, sites, monthly enrolment & "
                     "cost metrics, milestones, investigators & capacity, "
                     "safety events, region marts). Use for quantitative, "
                     "trend and count questions."),
        args_model=QueryStructuredArgs,
        handler=impl.query_structured_data,
        result_kind="structured",
    ),
    "get_entity": ToolSpec(
        name="get_entity",
        description="Fetch one entity by id with its relationships.",
        args_model=GetEntityArgs,
        handler=impl.get_entity,
        result_kind="entity",
    ),
    "get_relationships": ToolSpec(
        name="get_relationships",
        description="List relationships of an entity, optionally filtered by relation.",
        args_model=GetRelationshipsArgs,
        handler=impl.get_relationships,
        result_kind="relationships",
    ),
    "retrieve_document": ToolSpec(
        name="retrieve_document",
        description="Fetch a full document (bounded text) by id.",
        args_model=RetrieveDocumentArgs,
        handler=impl.retrieve_document,
        result_kind="document",
    ),
    "verify_claim": ToolSpec(
        name="verify_claim",
        description=("Check a claim against the current evidence ledger; "
                     "returns supported/unsupported with the validated "
                     "evidence ids."),
        args_model=VerifyClaimArgs,
        handler=impl.verify_claim,
        result_kind="verification",
    ),
}


def validate_args(name: ToolName, args: dict[str, Any]) -> BaseModel:
    spec = REGISTRY[name]
    return spec.args_model.model_validate(args)


def tool_descriptions() -> list[dict[str, str]]:
    """JSON-ish descriptions for planner prompts and MCP server."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "args_schema": str(spec.args_model.model_json_schema()),
        }
        for spec in REGISTRY.values()
    ]
