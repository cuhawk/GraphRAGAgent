"""RDF knowledge graph store (pyoxigraph) with per-document provenance graphs.

- Default graph: entity/relationship/attribute triples (ontology + generated
  data).
- Named graph per document (``https://nexusgraph.dev/graph/document/<id>``):
  DOCUMENT_MENTIONS triples derived from that document's text at ingestion,
  so every derived triple's provenance is the graph it lives in.
"""

from __future__ import annotations

import pathlib
import time

import pyoxigraph as ox

from nexusgraph.domain.ids import ONTOLOGY_BASE, document_graph_uri, document_uri
from nexusgraph.domain.models import SparqlResult
from nexusgraph.observability.logging import get_logger
from nexusgraph.security.sparqlguard import validate_sparql
from nexusgraph.utils import ToolTimeoutError, run_with_timeout

logger = get_logger("store.graph")

_MENTION = ox.NamedNode(f"{ONTOLOGY_BASE}DOCUMENT_MENTIONS")

QUERY_WALL_CLOCK_S = 20.0


class GraphStore:
    """Read-only SPARQL access over an embedded pyoxigraph store."""

    def __init__(self, path: pathlib.Path | str | None = None) -> None:
        if path is None or str(path) == ":memory:":
            self._store = ox.Store()
        else:
            p = pathlib.Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._store = ox.Store(str(p))

    # ------------------------------------------------------------------ load
    def load_ontology(self, path: pathlib.Path) -> None:
        self._store.load(path=path, format=ox.RdfFormat.TURTLE)

    def load_data(self, path: pathlib.Path) -> None:
        """Bulk-load generated entity/relationship data (default graph)."""
        self._store.load(path=path, format=ox.RdfFormat.TURTLE)

    def add_document_entity(self, document_id: str, title: str, content_type: str,
                            document_date: str | None, entity_uris: list[str]) -> int:
        """Write the document entity (rdf:type, title, ...) plus DOCUMENT_MENTIONS
        triples into the document's named graph — full provenance scoping."""
        graph = ox.NamedNode(document_graph_uri(document_id))
        doc = ox.NamedNode(document_uri(document_id))
        ngx = ONTOLOGY_BASE
        rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        self._store.add(ox.Quad(doc, ox.NamedNode(rdf_type),
                                ox.NamedNode(f"{ngx}ResearchDocument"), graph))
        self._store.add(ox.Quad(doc, ox.NamedNode(f"{ngx}title"),
                                ox.Literal(title), graph))
        self._store.add(ox.Quad(doc, ox.NamedNode(f"{ngx}contentType"),
                                ox.Literal(content_type), graph))
        if document_date:
            xsd_date = "http://www.w3.org/2001/XMLSchema#date"
            self._store.add(ox.Quad(doc, ox.NamedNode(f"{ngx}documentDate"),
                                    ox.Literal(document_date, datatype=ox.NamedNode(xsd_date)),
                                    graph))
        for uri in entity_uris:
            self._store.add(ox.Quad(doc, _MENTION, ox.NamedNode(uri), graph))
        return len(entity_uris)

    def add_document_mentions(self, document_id: str, entity_uris: list[str]) -> int:
        """Write DOCUMENT_MENTIONS triples into the document's named graph."""
        graph = ox.NamedNode(document_graph_uri(document_id))
        doc = ox.NamedNode(document_uri(document_id))
        for uri in entity_uris:
            self._store.add(ox.Quad(doc, _MENTION, ox.NamedNode(uri), graph))
        return len(entity_uris)

    def count(self) -> int:
        return len(self._store)

    # ----------------------------------------------------------------- query
    def query(
        self,
        sparql: str,
        *,
        max_rows: int = 200,
        include_named_graphs: bool = False,
        timeout_s: float = QUERY_WALL_CLOCK_S,
    ) -> SparqlResult:
        """Validate and execute a read-only SPARQL query.

        The query string is treated as untrusted and must pass the SPARQL
        guard. ``include_named_graphs`` widens the default graph to the whole
        dataset (including per-document mention graphs).
        """
        clean = validate_sparql(sparql)
        started = time.perf_counter()
        kwargs: dict[str, object] = {}
        if include_named_graphs:
            kwargs["use_default_graph_as_union"] = True

        def _run() -> tuple[list[str], list[dict[str, str]], bool] | bool:
            # Materialise rows inside the worker thread: pyoxigraph's solution
            # iterator must be consumed on the thread that created it.
            result = self._store.query(clean, **kwargs)  # type: ignore[arg-type]
            if isinstance(result, ox.QueryBoolean):
                return bool(result)
            variables = [v.value for v in result.variables]
            rows: list[dict[str, str]] = []
            truncated = False
            for solution in result:
                if len(rows) >= max_rows:
                    truncated = True
                    break
                row = {}
                for var in variables:
                    term = solution[var]
                    row[var] = term.value if term is not None else ""
                rows.append(row)
            return variables, rows, truncated

        try:
            outcome = run_with_timeout(_run, timeout_s)
        except ToolTimeoutError:
            logger.warning("sparql timed out")
            raise

        if isinstance(outcome, bool):
            return SparqlResult(
                query=clean, variables=["ask"],
                rows=[{"ask": "true" if outcome else "false"}],
                row_count=1,
            )

        variables, rows, truncated = outcome
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info("sparql ok", extra={"tool": "run_sparql", "duration_ms": elapsed_ms})
        return SparqlResult(query=clean, variables=variables, rows=rows,
                            row_count=len(rows), truncated=truncated)
