"""Tool implementations.

Every tool: typed args -> typed result, guarded inputs, capped outputs,
per-call span in the trace. The orchestrator converts results into Evidence;
tools themselves never emit citations (single responsibility).
"""

from __future__ import annotations

from nexusgraph.domain.models import (
    ClaimVerification,
    DocumentDetail,
    EntityDetail,
    Relationship,
    SearchHit,
    SparqlResult,
    StructuredQueryResult,
)
from nexusgraph.observability.logging import get_logger
from nexusgraph.tools.base import ToolContext, ToolError
from nexusgraph.tools.schemas import (
    GetEntityArgs,
    GetRelationshipsArgs,
    QueryStructuredArgs,
    RetrieveDocumentArgs,
    RunSparqlArgs,
    SearchDocumentsArgs,
    VerifyClaimArgs,
)
from nexusgraph.utils import ToolTimeoutError

logger = get_logger("tools")


def search_documents(ctx: ToolContext, args: SearchDocumentsArgs) -> list[SearchHit]:
    hits = ctx.runtime.retrieval.search(
        args.query,
        k=min(args.k, ctx.limits.retrieval_k * 2),
        document_ids=args.document_ids or None,
        entity_ids=args.entity_ids or None,
        content_types=args.content_types or None,
    )
    # Defensive double-cap on returned characters (THREAT_MODEL).
    kept: list[SearchHit] = []
    budget = ctx.limits.max_retrieval_chars
    for hit in hits:
        if budget - len(hit.text) < 0 and kept:
            break
        budget -= len(hit.text)
        kept.append(hit)
    return kept


def run_sparql(ctx: ToolContext, args: RunSparqlArgs) -> SparqlResult:
    try:
        return ctx.runtime.graph.query(
            args.query,
            max_rows=ctx.limits.max_rows,
            include_named_graphs=args.include_named_graphs,
            timeout_s=ctx.limits.sparql_timeout_s,
        )
    except ToolTimeoutError:
        raise
    except Exception as exc:
        raise ToolError(f"SPARQL execution failed: {exc}") from exc


def query_structured_data(
    ctx: ToolContext,
    args: QueryStructuredArgs,
) -> StructuredQueryResult:
    from nexusgraph.store.structured import run_structured_query

    try:
        return run_structured_query(ctx.runtime.engine, args.spec, ctx.limits)
    except ToolTimeoutError:
        raise
    except Exception as exc:
        raise ToolError(f"structured query failed: {exc}") from exc


def get_entity(ctx: ToolContext, args: GetEntityArgs) -> EntityDetail | None:
    return ctx.runtime.entities.get_entity_detail(args.entity_id)


def get_relationships(ctx: ToolContext, args: GetRelationshipsArgs) -> list[Relationship]:
    rels = ctx.runtime.entities.get_relationships(args.entity_id, relation=args.relation)
    return rels[: ctx.limits.max_rows]


def retrieve_document(ctx: ToolContext, args: RetrieveDocumentArgs) -> DocumentDetail | None:
    document = ctx.runtime.documents.get_document(args.document_id)
    if document is None:
        return None
    half = ctx.limits.max_result_bytes // 2
    if len(document.text) > half:
        document = document.model_copy(update={"text": document.text[:half] + " …[truncated]"})
    chunks = ctx.runtime.documents.chunks_for_document(document.id)
    return DocumentDetail(document=document, chunk_count=len(chunks))


def verify_claim(ctx: ToolContext, args: VerifyClaimArgs) -> ClaimVerification:
    """Deterministic structural verification.

    A claim is 'supported' when every referenced evidence id resolves in the
    orchestrator's evidence ledger (passed through ``ctx.known_evidence_ids``).
    Semantic LLM judgement is layered on top in the agent package when a real
    model is configured; this deterministic check is always applied last, so
    fabricated citations can never pass.
    """
    known = ctx.known_evidence_ids or set()
    if not args.evidence_ids:
        return ClaimVerification(
            supported=False,
            verdict="unsupported",
            rationale="no evidence references supplied for the claim",
            evidence_ids=[],
        )
    missing = [e for e in args.evidence_ids if e not in known]
    if missing:
        return ClaimVerification(
            supported=False,
            verdict="insufficient_evidence",
            rationale=f"evidence references not found in ledger: {missing}",
            evidence_ids=[e for e in args.evidence_ids if e not in missing],
        )
    return ClaimVerification(
        supported=True,
        verdict="supported",
        rationale="all evidence references resolve to retrieved evidence",
        evidence_ids=args.evidence_ids,
    )
