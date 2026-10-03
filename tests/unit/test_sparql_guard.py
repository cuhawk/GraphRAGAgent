import pytest

from nexusgraph.security.sparqlguard import SparqlGuardError, validate_sparql

OK_PREFIX = "PREFIX ngx: <https://nexusgraph.dev/ontology#>\n"


@pytest.mark.parametrize(
    "query",
    [
        "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5",
        OK_PREFIX + "SELECT ?name WHERE { ?t ngx:name ?name } ORDER BY ?name LIMIT 3",
        "ASK { ?s ?p ?o }",
        "# a comment with DROP keyword\nSELECT ?s WHERE { ?s ?p ?o }",
    ],
)
def test_valid_queries_pass(query: str) -> None:
    validated = validate_sparql(query)
    # Prologue is preserved; the query itself must still start with SELECT/ASK.
    assert "SELECT" in validated.split("{", 1)[0] or validated.startswith("ASK")


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <urn:a> <urn:b> <urn:c> }",
        "DELETE WHERE { ?s ?p ?o }",
        "LOAD <https://evil.example/x.ttl>",
        "SELECT * WHERE { SERVICE <https://evil.example/sparql> { ?s ?p ?o } }",
        "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "DESCRIBE <urn:a>",
        "DROP GRAPH <urn:g>",
        "CLEAR ALL",
        "SELECT ?s WHERE { ?s ?p ?o } ; DROP ALL",
        "",
        "   ",
    ],
)
def test_malicious_queries_rejected(query: str) -> None:
    with pytest.raises(SparqlGuardError):
        validate_sparql(query)


def test_query_too_long_rejected() -> None:
    query = "SELECT ?s WHERE { ?s ?p ?o } FILTER(?s = <urn:" + "x" * 5000 + ">)"
    with pytest.raises(SparqlGuardError, match="too long"):
        validate_sparql(query)


def test_keyword_hidden_in_comment_is_stripped() -> None:
    query = "SELECT ?s WHERE { ?s <urn:p> ?o } # SERVICE <https://x>"
    assert validate_sparql(query).startswith("SELECT")
