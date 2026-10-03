"""Security-focused tests: guard evasion, parameterisation, budgets,
evidence integrity and named-graph isolation (docs/THREAT_MODEL.md)."""

from __future__ import annotations

import pytest

from nexusgraph.domain.models import Aggregation, FilterCondition, QuerySpec
from nexusgraph.security.sparqlguard import validate_sparql
from nexusgraph.security.sqlguard import SqlGuardError, validate_query_spec
from nexusgraph.store.structured import STRUCTURED_SCHEMA
from nexusgraph.tools.base import ToolBudget, ToolBudgetExceeded


def test_iri_with_hash_is_not_treated_as_comment() -> None:
    query = ("PREFIX ngx: <https://nexusgraph.dev/ontology#>\n"
             "SELECT ?n WHERE { ?s ngx:name ?n } # trailing comment")
    validated = validate_sparql(query)
    assert "ngx:name" in validated  # the IRI must survive comment stripping


def test_parameterised_filters_never_execute_injected_sql(seeded_engine,
                                                          limits) -> None:
    """Filter values travel as bound parameters, never as SQL text."""
    from nexusgraph.store.structured import run_structured_query

    evil = "S-1001'; DROP TABLE sites; --"
    spec = QuerySpec(table="sites",
                     filters=[FilterCondition(column="site_id", op="eq",
                                              value=evil)])
    result = run_structured_query(seeded_engine, spec, limits)
    assert result.row_count == 0  # no row matches; nothing was executed
    # the table must still exist and be intact
    intact = run_structured_query(seeded_engine, QuerySpec(table="sites"),
                                  limits)
    assert intact.row_count > 0


def test_oversized_filter_value_rejected() -> None:
    spec = QuerySpec(table="sites",
                     filters=[FilterCondition(column="site_id", op="eq",
                                              value="x" * 300)])
    with pytest.raises(SqlGuardError, match="too long"):
        validate_query_spec(spec, STRUCTURED_SCHEMA)


def test_non_scalar_filter_value_rejected() -> None:
    spec = QuerySpec(table="sites",
                     filters=[FilterCondition(column="site_id", op="eq",
                                              value={"$ne": None})])
    with pytest.raises(SqlGuardError, match="unsupported filter value"):
        validate_query_spec(spec, STRUCTURED_SCHEMA)


def test_tool_budget_blocks_excess_calls() -> None:
    budget = ToolBudget(max_calls=2)
    budget.acquire("search_documents")
    budget.acquire("run_sparql")
    with pytest.raises(ToolBudgetExceeded):
        budget.acquire("run_sparql")
    assert budget.calls_by_tool == {"search_documents": 1, "run_sparql": 1}


def test_verify_claim_rejects_fabricated_evidence(graph_store, entity_store,
                                                  engine, limits) -> None:
    """The deterministic verifier: only ledger-known evidence ids pass."""
    from nexusgraph.tools.base import ToolContext
    from nexusgraph.tools.implementations import verify_claim
    from nexusgraph.tools.schemas import VerifyClaimArgs

    ctx = ToolContext(runtime=None, limits=limits, budget=ToolBudget(5),
                      known_evidence_ids={"ev-0001"})
    ok = verify_claim(ctx, VerifyClaimArgs(claim="x", evidence_ids=["ev-0001"]))
    assert ok.supported

    fabricated = verify_claim(ctx, VerifyClaimArgs(
        claim="x", evidence_ids=["ev-9999"]))
    assert not fabricated.supported
    assert fabricated.verdict == "insufficient_evidence"

    empty = verify_claim(ctx, VerifyClaimArgs(claim="x", evidence_ids=[]))
    assert not empty.supported
    assert empty.verdict == "unsupported"


def test_mention_graphs_hidden_without_union(graph_store) -> None:
    """Per-document mention triples live in named graphs and are invisible
    to default-graph queries (privacy boundary / provenance scoping)."""
    graph_store.add_document_entity(
        "doc:D-9001", "Test document", "text/markdown", None,
        ["https://nexusgraph.dev/data/Site/S-1001"])

    hidden = graph_store.query(
        "SELECT ?d WHERE { ?d <https://nexusgraph.dev/ontology#DOCUMENT_MENTIONS> ?e }")
    visible = graph_store.query(
        "SELECT ?d WHERE { ?d <https://nexusgraph.dev/ontology#DOCUMENT_MENTIONS> ?e }",
        include_named_graphs=True)
    assert hidden.row_count == 0
    assert visible.row_count == 1


def test_row_cap_and_truncation_flag(graph_store) -> None:
    result = graph_store.query(
        "SELECT ?s WHERE { ?s ?p ?o }", max_rows=2)
    assert result.row_count == 2
    assert result.truncated


def test_ask_form_allowed(graph_store) -> None:
    ask = graph_store.query("ASK { ?s ?p ?o }")
    assert ask.rows == [{"ask": "true"}]


def test_aggregation_without_column_only_for_count() -> None:
    spec = QuerySpec(table="site_metrics_monthly",
                     aggregations=[Aggregation(func="sum", column=None)])
    with pytest.raises(SqlGuardError, match="aggregation without a column"):
        validate_query_spec(spec, STRUCTURED_SCHEMA)
