import pytest

from nexusgraph.security.sparqlguard import SparqlGuardError
from nexusgraph.store.graph import GraphStore

PREFIX = (
    "PREFIX ngx: <https://nexusgraph.dev/ontology#>\nPREFIX nxg: <https://nexusgraph.dev/data/>\n"
)


def test_count_and_type_query(graph_store: GraphStore) -> None:
    result = graph_store.query(
        PREFIX + ("SELECT (COUNT(?t) AS ?n) WHERE { ?t a ngx:ClinicalTrial }")
    )
    assert int(result.rows[0]["n"]) >= 10


def test_trial_sites_traversal(graph_store: GraphStore) -> None:
    result = graph_store.query(
        PREFIX
        + (
            "SELECT ?site WHERE { ?t ngx:name 'AURORA-2' . "
            "?t ngx:TRIAL_HAS_SITE ?site } ORDER BY ?site"
        )
    )
    sites = {row["site"].rsplit("/", 1)[-1] for row in result.rows}
    assert {"S-1001", "S-1002"} <= sites


def test_ask_query(graph_store: GraphStore) -> None:
    result = graph_store.query(PREFIX + "ASK { ?s ngx:severity 'HIGH' }")
    assert result.rows[0]["ask"] == "true"


def test_guard_rejects_update_via_store(graph_store: GraphStore) -> None:
    with pytest.raises(SparqlGuardError):
        graph_store.query("INSERT DATA { <urn:a> <urn:b> <urn:c> }")


def test_document_mentions_named_graph(graph_store: GraphStore) -> None:
    graph_store.add_document_mentions(
        "D-9001",
        ["https://nexusgraph.dev/data/site/S-1001", "https://nexusgraph.dev/data/trial/T-2001"],
    )
    # Not visible in the default graph
    result = graph_store.query(
        PREFIX + ("SELECT (COUNT(?m) AS ?n) WHERE { ?d ngx:DOCUMENT_MENTIONS ?m }")
    )
    assert int(result.rows[0]["n"]) == 0
    # Visible when named graphs are included
    result = graph_store.query(
        PREFIX + ("SELECT (COUNT(?m) AS ?n) WHERE { ?d ngx:DOCUMENT_MENTIONS ?m }"),
        include_named_graphs=True,
    )
    assert int(result.rows[0]["n"]) == 2


def test_row_cap_and_truncation(graph_store: GraphStore) -> None:
    result = graph_store.query(PREFIX + "SELECT ?n WHERE { ?s ngx:name ?n }", max_rows=3)
    assert result.row_count == 3
    assert result.truncated is True
