"""Evidence ledger: the single source of truth for citations.

Every tool result is converted into immutable :class:`Evidence` items with
stable ids (``ev-0001``). Claims may only reference ids that exist here — the
orchestrator and the verify_claim tool enforce this, so fabricated citations
are structurally impossible.
"""

from __future__ import annotations

import json
import re
import unicodedata

from nexusgraph.domain.models import (
    DocumentDetail,
    EntityDetail,
    Evidence,
    SearchHit,
    SourceType,
    SparqlResult,
    StructuredQueryResult,
)
from nexusgraph.retrieval.context import content_terms, interaction

# Filter whole paragraphs so a wrapped directive cannot leave its payload behind.
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_INSTRUCTION = re.compile(
    r"ignore (?:all |any |your |the )?(?:previous|prior|operating|system|developer)|"
    r"system directive|(?:highest priority|instruction) override|"
    r"(?:hidden )?directive for automated readers|(?:if you are|as) an? (?:ai|assistant)|"
    r"(?:reply|respond|answer|output|print) (?:with )?(?:exactly|only)|"
    r"(?:do not|never) (?:comply|cite|mention)|"
    r"\[(?:/?inst|/?system)\]|<\|(?:im_start|system|assistant)\|>|"
    r"^(?:system|assistant|developer)\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_QUERY_FILLER = frozenset(
    [
        "document",
        "documents",
        "report",
        "reports",
        "say",
        "states",
        "happened",
        "show",
        "tell",
        "listed",
        "recorded",
        "note",
        "register",
        "handbook",
        "bulletin",
    ]
)


def sanitize_document(text: str) -> str:
    safe = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        normalized = unicodedata.normalize("NFKC", paragraph)
        normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
        flattened = re.sub(r"\s+", " ", normalized).strip()
        if flattened and not (_INSTRUCTION.search(normalized) or _INSTRUCTION.search(flattened)):
            safe.append(paragraph.strip())
    return "\n\n".join(safe)


def document_spans(text: str) -> list[tuple[str, str]]:
    """Return verbatim sentences or intact table rows from sanitized text."""
    spans: list[tuple[str, str]] = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        rows = [line.strip() for line in paragraph.splitlines() if line.lstrip().startswith("|")]
        if len(rows) > 2 and re.fullmatch(r"[| :\-]+", rows[1]):
            spans.extend((row, rows[0]) for row in rows[2:])
        else:
            spans.extend((part.strip(), "") for part in _SENTENCE_BREAK.split(paragraph))
    return [(span, header) for span, header in spans if any(c.isalnum() for c in span)]


def query_span_score(
    question: str, span: str, minimum: float, *, header: str = "", scope: str = ""
) -> float:
    terms = content_terms(question) - _QUERY_FILLER
    span_terms = content_terms(span)
    found = content_terms(header) | span_terms
    identifiers = {term for term in terms if any(c.isdigit() for c in term)}
    scope_terms = content_terms(scope) if not header else set()
    if identifiers and identifiers <= scope_terms and terms - scope_terms:
        # A title can establish the record being discussed. Require the passage
        # itself to cover the requested information outside that title.
        terms -= scope_terms
    if (
        not terms
        or not identifiers <= span_terms | scope_terms
        or sum(term in found or term + "s" in found for term in terms) < min(2, len(terms))
    ):
        return 0.0
    if not identifiers and len(terms) >= 5:
        minimum = max(minimum, 0.85)
    similarity, coverage = interaction(" ".join(sorted(terms)), f"{header} {span}")
    if coverage < minimum:
        return 0.0
    if header and "register" in content_terms(question):
        similarity += 0.15
    return similarity


def claim_matches_span(claim: str, span: str) -> bool:
    phrase = " ".join(claim.casefold().split()).rstrip(".")
    source = " ".join(span.casefold().split()).rstrip(".")
    return bool(phrase and phrase == source)


_DATA_BASE = "https://nexusgraph.dev/data/"
MAX_EVIDENCE_PER_TOOL = 10
SNIPPET_CHARS = 280

# Preferred key columns for the per-row evidence location; combined so that
# grouped series rows (site_id + month) each get distinct, citable evidence.
_ROW_KEY_COLUMNS = (
    "site_id",
    "region_id",
    "trial_id",
    "compound_id",
    "investigator_id",
    "milestone_id",
    "event_id",
    "product_id",
    "company_id",
    "country_id",
    "month",
    "reported_at",
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

    def _add(
        self,
        source_id: str,
        source_type: SourceType,
        location: str,
        *,
        snippet: str | None = None,
        uri: str | None = None,
        confidence: float = 1.0,
        scope: str = "",
        snippet_limit: int | None = SNIPPET_CHARS,
    ) -> Evidence | None:
        key = (source_id, location)
        if key in self._seen or len(self._items) >= self._max:
            return None
        self._seen.add(key)
        evidence = Evidence(
            evidence_id=f"ev-{len(self._items) + 1:04d}",
            source_id=source_id,
            source_type=source_type,
            location=location,
            snippet=(snippet[:snippet_limit] if snippet else None),
            uri=uri,
            confidence=confidence,
            scope=scope,
        )
        self._items.append(evidence)
        return evidence

    # ------------------------------------------------------------ converters
    def add_search_hits(self, hits: list[SearchHit]) -> list[Evidence]:
        added = []
        for hit in hits:
            snippet = sanitize_document(
                hit.source_text if hit.source_text is not None else hit.text
            )
            if not snippet:
                continue
            evidence = self._add(
                source_id=hit.document_id,
                source_type=SourceType.document,
                location=hit.citation or hit.chunk_id,
                snippet=snippet,
                snippet_limit=None,
                scope=sanitize_document(hit.document_title or ""),
            )
            if evidence:
                added.append(evidence)
        return added

    def add_structured(self, result: StructuredQueryResult, table: str) -> list[Evidence]:
        added = []
        for row in result.rows[:MAX_EVIDENCE_PER_TOOL]:
            added.append(
                self._add(
                    source_id=f"sql:{table}",
                    source_type=SourceType.sql,
                    location=f"{table}:{_row_key(row)}",
                    snippet=json.dumps(row, default=str)[:SNIPPET_CHARS],
                )
            )
        return [e for e in added if e]

    def add_sparql(self, result: SparqlResult) -> list[Evidence]:
        added = []
        for row in result.rows[:MAX_EVIDENCE_PER_TOOL]:
            uri = next((v for v in row.values() if v.startswith(_DATA_BASE)), None)
            location = ", ".join(f"{k}={_short(v)}" for k, v in row.items() if v)[:SNIPPET_CHARS]
            added.append(
                self._add(
                    source_id=uri or f"sparql:{abs(hash(result.query)) % 10_000_000}",
                    source_type=SourceType.rdf,
                    location=location or "sparql-binding",
                    snippet=json.dumps(row, default=str)[:SNIPPET_CHARS],
                    uri=uri,
                )
            )
        return [e for e in added if e]

    def add_document(self, detail: DocumentDetail) -> Evidence | None:
        snippet = sanitize_document(detail.document.text)
        if not snippet:
            return None
        return self._add(
            source_id=detail.document.id,
            source_type=SourceType.document,
            location="document",
            snippet=snippet,
            snippet_limit=None,
            scope=sanitize_document(detail.document.title),
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
