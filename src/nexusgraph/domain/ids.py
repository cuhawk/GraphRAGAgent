"""Entity/URI identity scheme.

- In-code entity ids are ``<type>:<local_id>``, e.g. ``trial:T-1001``.
- RDF subjects use ``https://nexusgraph.dev/data/<type>/<local_id>``.
- The ontology lives at ``https://nexusgraph.dev/ontology#`` (prefix ``ngx:``).

Keeping this mapping in one place makes round-tripping between SQL rows,
RDF triples and API payloads lossless.
"""

from __future__ import annotations

ONTOLOGY_BASE = "https://nexusgraph.dev/ontology#"
DATA_BASE = "https://nexusgraph.dev/data/"
GRAPH_BASE = "https://nexusgraph.dev/graph/"


def entity_uri(entity_type: str, local_id: str) -> str:
    return f"{DATA_BASE}{entity_type}/{local_id}"


def parse_entity_uri(uri: str) -> tuple[str, str] | None:
    """Return ``(entity_type, local_id)`` for data URIs, else ``None``."""
    if not uri.startswith(DATA_BASE):
        return None
    rest = uri[len(DATA_BASE) :]
    if "/" not in rest:
        return None
    entity_type, _, local_id = rest.partition("/")
    if not entity_type or not local_id:
        return None
    return entity_type, local_id


def entity_id(entity_type: str, local_id: str) -> str:
    return f"{entity_type}:{local_id}"


def split_entity_id(entity_id: str) -> tuple[str, str] | None:
    """Return ``(entity_type, local_id)`` for ``type:local`` ids, else ``None``."""
    if ":" not in entity_id:
        return None
    entity_type, _, local_id = entity_id.partition(":")
    if not entity_type or not local_id:
        return None
    return entity_type, local_id


def document_uri(document_id: str) -> str:
    return f"{DATA_BASE}document/{document_id}"


def document_graph_uri(document_id: str) -> str:
    """Named graph holding triples derived from one document (provenance scoping)."""
    return f"{GRAPH_BASE}document/{document_id}"
