"""SPARQL query builders used by the orchestrator.

Queries are parameterised here (never free-text from the model in heuristic
mode) but they still pass the SPARQL guard on every execution - the guard is
the boundary, not the builder. In LLM mode the model may also emit raw SPARQL,
which is why the guard exists.
"""

from __future__ import annotations

PREFIX_BLOCK = (
    "PREFIX ngx: <https://nexusgraph.dev/ontology#>\nPREFIX nxg: <https://nexusgraph.dev/data/>\n"
)


def _uri(entity_id: str) -> str:
    entity_type, local = entity_id.split(":", 1)
    return f"https://nexusgraph.dev/data/{entity_type}/{local}"


def compounds_of_trial(trial_id: str) -> str:
    return PREFIX_BLOCK + (
        f"SELECT ?compound ?name WHERE {{ "
        f"<{_uri(trial_id)}> ngx:TRIAL_USES_COMPOUND ?compound . "
        f"?compound ngx:name ?name }} ORDER BY ?compound"
    )


def products_of_trial(trial_id: str) -> str:
    return PREFIX_BLOCK + (
        f"SELECT DISTINCT ?product ?name WHERE {{ "
        f"<{_uri(trial_id)}> ngx:TRIAL_USES_COMPOUND ?compound . "
        f"?product ngx:PRODUCT_DERIVED_FROM ?compound . "
        f"?product ngx:name ?name }} ORDER BY ?product"
    )


def documents_mentioning(entity_ids: list[str]) -> str:
    uris = ", ".join(f"<{_uri(e)}>" for e in entity_ids)
    return PREFIX_BLOCK + (
        f"SELECT DISTINCT ?document ?title WHERE {{ "
        f"?document ngx:DOCUMENT_MENTIONS ?e . "
        f"FILTER(?e IN ({uris})) "
        f"?document ngx:title ?title }} ORDER BY ?document"
    )


def documents_mentioning_compounds_of_trial(trial_id: str) -> str:
    """trial -> compounds -> (mention named graphs) -> documents (3-hop)."""
    return PREFIX_BLOCK + (
        f"SELECT DISTINCT ?document ?title ?compound WHERE {{ "
        f"<{_uri(trial_id)}> ngx:TRIAL_USES_COMPOUND ?compound . "
        f"?document ngx:DOCUMENT_MENTIONS ?compound . "
        f"?document ngx:title ?title }} ORDER BY ?document"
    )


def delayed_milestones_with_trials() -> str:
    return PREFIX_BLOCK + (
        "SELECT ?milestone ?trial ?due ?completed WHERE { "
        "?milestone ngx:dueDate ?due . "
        "?milestone ngx:completedDate ?completed . "
        "FILTER(?completed > ?due) "
        "?trial ngx:TRIAL_HAS_MILESTONE ?milestone } ORDER BY ?trial"
    )


def products_of_delayed_trials() -> str:
    return PREFIX_BLOCK + (
        "SELECT DISTINCT ?product ?name WHERE { "
        "?milestone ngx:dueDate ?due . "
        "?milestone ngx:completedDate ?completed . "
        "FILTER(?completed > ?due) "
        "?trial ngx:TRIAL_HAS_MILESTONE ?milestone . "
        "?trial ngx:TRIAL_USES_COMPOUND ?compound . "
        "?product ngx:PRODUCT_DERIVED_FROM ?compound . "
        "?product ngx:name ?name } ORDER BY ?product"
    )


def safety_events_at_site(site_id: str) -> str:
    return PREFIX_BLOCK + (
        f"SELECT ?event ?severity ?reported WHERE {{ "
        f"?event ngx:SAFETY_EVENT_AT_SITE <{_uri(site_id)}> . "
        f"?event ngx:severity ?severity . "
        f"?event ngx:reportedAt ?reported }} ORDER BY DESC(?reported)"
    )


def sites_of_trial(trial_id: str) -> str:
    return PREFIX_BLOCK + (
        f"SELECT ?site ?name WHERE {{ "
        f"<{_uri(trial_id)}> ngx:TRIAL_HAS_SITE ?site . "
        f"?site ngx:name ?name }} ORDER BY ?site"
    )


def compounds_with_safety_reports_and_sites() -> str:
    """Compounds named in operational safety reports, and the trial sites
    associated with them (via trials using the compound). Powers the
    'falling enrolment + safety-report compounds' mixed question."""
    return PREFIX_BLOCK + (
        "SELECT DISTINCT ?site ?name ?compound WHERE { "
        "?event ngx:SAFETY_EVENT_INVOLVES_COMPOUND ?compound . "
        "?trial ngx:TRIAL_USES_COMPOUND ?compound . "
        "?trial ngx:TRIAL_HAS_SITE ?site . "
        "?site ngx:name ?name } ORDER BY ?site"
    )


def entity_neighbours(entity_id: str) -> str:
    return PREFIX_BLOCK + (
        f"SELECT ?p ?o WHERE {{ <{_uri(entity_id)}> ?p ?o }} ORDER BY ?p LIMIT 50"
    )


def trials_of_compound(compound_id: str) -> str:
    return PREFIX_BLOCK + (
        f"SELECT ?trial ?name WHERE {{ "
        f"?trial ngx:TRIAL_USES_COMPOUND <{_uri(compound_id)}> . "
        f"?trial ngx:name ?name }} ORDER BY ?trial"
    )
