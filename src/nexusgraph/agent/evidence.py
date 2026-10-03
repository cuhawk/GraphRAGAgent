"""Evidence ledger: the single source of truth for citations.

Every tool result is converted into immutable :class:`Evidence` items with
stable ids (``ev-0001``). Claims may only reference ids that exist here — the
orchestrator and the verify_claim tool enforce this, so fabricated citations
are structurally impossible.
"""

from __future__ import annotations

import json

from nexusgraph.domain.models import (
    DocumentDetail,
    EntityDetail,
    Evidence,
    SearchHit,
    SourceType,
    SparqlResult,
    StructuredQueryResult,
)

_DATA_BASE = "https://nexusgraph.dev/data/"
MAX_EVIDENCE_PER_TOOL = 10
SNIPPET_CHARS = 280

# Preferred key columns for the per-row evidence location; combined so that
# grouped series rows (site_id + month) each get distinct, citable evidence.
_ROW_KEY_COLUMNS = (
    "site_id", "region_id", "trial_id", "compound_id", "investigator_id",
    "milestone_id", "event_id", "product_id", "company_id", "country_id",
    "month", "reported_at",
)


def _row_key(row: dict) -> str:
    parts = [str(row[col]) for col in _ROW_KEY_COLUMNS if row.get(col) is not None]
    return ":".join(parts) if parts else "row"


class EvidenceLedger:
    def __init__(self, max_items: int = 80) -> None:
        self._items: list[Evidence] = []
        self._seen: set[tuple[str, str]] = set()
        self._max = max_items

    def items(self) -> list[Evidence]:
        return list(self._items)

    def ids(self) -> set[str]:
        return {e.evidence_id for e in self._items}

    def get(self, evidence_id: str) -> Evidence | None:
        for evidence in self._items:
            if evidence.evidence_id == evidence_id:
                return evidence
        return None

    def by_source_type(self, source_type: SourceType) -> list[Evidence]:
        return [e for e in self._items if e.source_type == source_type]

    def _add(self, source_id: str, source_type: SourceType, location: str, *,
             snippet: str | None = None, uri: str | None = None,
             confidence: float = 1.0) -> Evidence | None:
        key = (source_id, location)
        if key in self._seen or len(self._items) >= self._max:
            return None
        self._seen.add(key)
        evidence = Evidence(
            evidence_id=f"ev-{len(self._items) + 1:04d}",
            source_id=source_id,
            source_type=source_type,
            location=location,
            snippet=(snippet[:SNIPPET_CHARS] if snippet else None),
            uri=uri,
            confidence=confidence,
        )
        self._items.append(evidence)
        return evidence

    # ------------------------------------------------------------ converters
    def add_search_hits(self, hits: list[SearchHit]) -> list[Evidence]:
        added = []
        for hit in hits:
            evidence = self._add(
                source_id=hit.document_id,
                source_type=SourceType.document,
                location=hit.chunk_id,
                snippet=hit.text,
            )
            if evidence:
                added.append(evidence)
        return added

    def add_structured(self, result: StructuredQueryResult, table: str) -> list[Evidence]:
        added = []
        for row in result.rows[:MAX_EVIDENCE_PER_TOOL]:
            added.append(self._add(
                source_id=f"sql:{table}",
                source_type=SourceType.sql,
                location=f"{table}:{_row_key(row)}",
                snippet=json.dumps(row, default=str)[:SNIPPET_CHARS],
            ))
        return [e for e in added if e]

    def add_sparql(self, result: SparqlResult) -> list[Evidence]:
        added = []
        for row in result.rows[:MAX_EVIDENCE_PER_TOOL]:
            uri = next((v for v in row.values() if v.startswith(_DATA_BASE)), None)
            location = ", ".join(f"{k}={_short(v)}" for k, v in row.items()
                                 if v)[:SNIPPET_CHARS]
            added.append(self._add(
                source_id=uri or f"sparql:{abs(hash(result.query)) % 10_000_000}",
                source_type=SourceType.rdf,
                location=location or "sparql-binding",
                snippet=json.dumps(row, default=str)[:SNIPPET_CHARS],
                uri=uri,
            ))
        return [e for e in added if e]

    def add_document(self, detail: DocumentDetail) -> Evidence | None:
        return self._add(
            source_id=detail.document.id,
            source_type=SourceType.document,
            location="document",
            snippet=detail.document.text[:SNIPPET_CHARS] or detail.document.title,
        )

    def add_entity(self, detail: EntityDetail) -> Evidence | None:
        entity = detail.entity
        local = entity.id.split(":", 1)[-1]
        return self._add(
            source_id=entity.id,
            source_type=SourceType.rdf,
            location=f"entity:{entity.type}",
            snippet=entity.description or entity.name,
            uri=f"{_DATA_BASE}{entity.type}/{local}",
        )


def _short(value: str) -> str:
    return value.rsplit("/", 1)[-1]
