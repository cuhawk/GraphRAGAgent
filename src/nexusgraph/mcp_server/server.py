"""MCP server: NexusGraph's read-only data tools over the Model Context
Protocol.

Properties (see docs/THREAT_MODEL.md):

- **Read-only**: only the data-access tools are exposed. There is no write,
  delete, ingestion or execution surface; SPARQL and structured queries still
  pass the same guards as the agent path.
- **Typed**: arguments are validated with the same Pydantic models the agent
  uses (single source of truth: :data:`nexusgraph.tools.registry.REGISTRY`).
- **Bounded**: outputs are JSON strings capped at ``limits.max_result_bytes``;
  per-call tool budgets and result caps still apply.

Run with ``nexusgraph mcp`` (stdio transport). ``http_app()`` returns a
streamable-HTTP ASGI app that the API server can mount.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from nexusgraph.config import Settings
from nexusgraph.domain.models import ToolName
from nexusgraph.observability.logging import get_logger
from nexusgraph.tools.base import ToolBudget, ToolContext
from nexusgraph.tools.registry import REGISTRY

logger = get_logger("mcp_server")

_DESCRIPTIONS = {
    "search_documents": ("Hybrid semantic search over the document corpus. "
                         "Returns chunks with scores."),
    "run_sparql": ("Run a read-only SPARQL SELECT/ASK query against the RDF "
                   "knowledge graph. PREFIXES: ngx: "
                   "<https://nexusgraph.dev/ontology#>, nxg: "
                   "<https://nexusgraph.dev/data/>. Guarded: SELECT/ASK only."),
    "query_structured_data": ("Run a typed aggregate/select over relational "
                              "tables via a QuerySpec dict (table, select, "
                              "filters, aggregations, group_by, order_by, "
                              "limit). Compiled to parameterised SQL."),
    "get_entity": "Fetch one knowledge-graph entity by id with relationships.",
    "get_relationships": ("List relationships of an entity, optionally "
                          "filtered by relation name."),
    "retrieve_document": "Fetch a full document (bounded text) by id.",
}


def _serialize(result: Any) -> Any:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, list):
        return [_serialize(item) for item in result]
    return result


def create_server(settings: Settings | None = None) -> MCPServer:
    """Build the MCP server bound to a bootstrapped runtime."""
    from nexusgraph.runtime import ensure_bootstrapped

    settings = settings or Settings()
    runtime, _bootstrapped = ensure_bootstrapped(settings)
    limits = settings.limits

    mcp: MCPServer = MCPServer(
        name="nexusgraph",
        instructions=("Read-only GraphRAG tools over a synthetic "
                      "life-sciences knowledge graph: SPARQL, typed SQL, "
                      "hybrid document retrieval and entity lookup. All "
                      "answers should cite the returned source ids."),
    )

    def _execute(name: ToolName, payload: dict[str, Any]) -> str:
        spec = REGISTRY[name]
        args = spec.args_model.model_validate(payload)
        ctx = ToolContext(runtime=runtime, limits=limits,
                          budget=ToolBudget(limits.max_tool_calls_per_run))
        result = spec.handler(ctx, args)
        text = json.dumps(_serialize(result), default=str, ensure_ascii=False)
        if len(text) > limits.max_result_bytes:
            text = text[: limits.max_result_bytes] + " …[truncated]"
        return text

    @mcp.tool(description=_DESCRIPTIONS["search_documents"])
    def search_documents(query: str, k: int = 6) -> str:
        return _execute("search_documents", {"query": query, "k": k})

    @mcp.tool(description=_DESCRIPTIONS["run_sparql"])
    def run_sparql(query: str, include_named_graphs: bool = False) -> str:
        return _execute("run_sparql", {"query": query,
                                       "include_named_graphs": include_named_graphs})

    @mcp.tool(description=_DESCRIPTIONS["query_structured_data"])
    def query_structured_data(spec: dict[str, Any]) -> str:
        return _execute("query_structured_data", {"spec": spec})

    @mcp.tool(description=_DESCRIPTIONS["get_entity"])
    def get_entity(entity_id: str) -> str:
        return _execute("get_entity", {"entity_id": entity_id})

    @mcp.tool(description=_DESCRIPTIONS["get_relationships"])
    def get_relationships(entity_id: str, relation: str | None = None) -> str:
        return _execute("get_relationships", {"entity_id": entity_id,
                                              "relation": relation})

    @mcp.tool(description=_DESCRIPTIONS["retrieve_document"])
    def retrieve_document(document_id: str) -> str:
        return _execute("retrieve_document", {"document_id": document_id})

    return mcp


def run_stdio(settings: Settings | None = None) -> int:
    """Entry point for ``nexusgraph mcp`` (stdio transport)."""
    server = create_server(settings)
    logger.info("starting nexusgraph MCP server (stdio)")
    server.run("stdio")
    return 0


def http_app(settings: Settings | None = None) -> Any:
    """Streamable-HTTP ASGI app for mounting into the API server."""
    return create_server(settings).streamable_http_app()
