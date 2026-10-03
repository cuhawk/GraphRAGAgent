"""SPARQL guard: the query string is untrusted input.

Allowed: SELECT and ASK over the read-only RDF store.
Denied:  any update operation (INSERT/DELETE/LOAD/CLEAR/CREATE/DROP/MOVE/COPY/
         ADD), federation (SERVICE) which would turn the graph store into an
         SSRF vector, and result-shaping forms (CONSTRUCT/DESCRIBE) that the
         tool contract does not support.

 Defence in depth: the DB/RDF user is read-only and results are row-capped;
 the wall-clock timeout is enforced by the tool layer.
"""

from __future__ import annotations

import re

from nexusgraph.observability.logging import get_logger

logger = get_logger("security.sparql")

MAX_QUERY_CHARS = 4_000

ALLOWED_FORMS = ("SELECT", "ASK")

_FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern, re.IGNORECASE | re.DOTALL))
    for name, pattern in [
        ("update_insert", r"\bINSERT\b"),
        ("update_delete", r"\bDELETE\b"),
        ("update_load", r"\bLOAD\b"),
        ("update_clear", r"\bCLEAR\b"),
        ("update_create", r"\bCREATE\b"),
        ("update_drop", r"\bDROP\b"),
        ("update_move", r"\bMOVE\b"),
        ("update_copy", r"\bCOPY\b"),
        ("update_add", r"\bADD\b"),
        ("federation_service", r"\bSERVICE\b"),
        ("non_select_form", r"\bCONSTRUCT\b"),
        ("non_select_form_describe", r"\bDESCRIBE\b"),
        ("silence_errors", r"\bSILENT\b"),
    ]
]

_PREFIX_RE = re.compile(r"^\s*PREFIX\s+[^\s]+\s+<[^\s]*>", re.IGNORECASE)
_BASE_RE = re.compile(r"^\s*BASE\s+<[^\s]*>", re.IGNORECASE)


class SparqlGuardError(ValueError):
    """Raised when a SPARQL query fails validation."""


def _strip_comments(query: str) -> str:
    """Remove ``# ...`` comments, honouring ``<iri>`` refs and quoted strings."""
    out: list[str] = []
    i, n = 0, len(query)
    in_iri = False
    quote: str | None = None
    while i < n:
        ch = query[i]
        if in_iri:
            out.append(ch)
            if ch == ">":
                in_iri = False
            i += 1
            continue
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(query[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == "<":
            in_iri = True
            out.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#":
            while i < n and query[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_prologue(query: str) -> str:
    """Remove leading PREFIX/BASE declarations (harmless prologue)."""
    while True:
        match = _PREFIX_RE.match(query) or _BASE_RE.match(query)
        if match is None:
            return query
        query = query[match.end() :]


def validate_sparql(query: str) -> str:
    """Validate an untrusted SPARQL query; returns the stripped query or raises."""
    if not query or not query.strip():
        raise SparqlGuardError("empty SPARQL query")
    if len(query) > MAX_QUERY_CHARS:
        raise SparqlGuardError(f"SPARQL query too long ({len(query)} chars, max {MAX_QUERY_CHARS})")

    stripped = _strip_comments(query)
    core = _strip_prologue(stripped)

    # First meaningful keyword (after the harmless prologue) must be SELECT/ASK.
    first_word = re.search(r"[A-Za-z]+", core)
    if first_word is None or first_word.group(0).upper() not in ALLOWED_FORMS:
        found = first_word.group(0).upper() if first_word else "<none>"
        raise SparqlGuardError(
            f"only {' / '.join(ALLOWED_FORMS)} queries are allowed, got: {found}"
        )

    for name, pattern in _FORBIDDEN_PATTERNS:
        match = pattern.search(stripped)
        if match:
            logger.warning("SPARQL guard denial (%s)", name)
            raise SparqlGuardError(f"SPARQL keyword not allowed: {name}")

    # The returned query keeps the prologue so prefixes still resolve.
    return " ".join(stripped.split())
