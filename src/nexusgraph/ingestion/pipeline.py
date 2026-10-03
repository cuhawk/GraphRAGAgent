"""Ingestion pipeline.

document file
  -> parse (parsers.py)
  -> normalize + chunk (chunking.py)
  -> entity extraction (extraction.py: deterministic default, LLM optional)
  -> entity resolution (resolution.py)
  -> embeddings (retrieval.embeddings)
  -> vector index (chunks table + vector index refresh)
  -> RDF triples: per-document named graph with rdf:type + DOCUMENT_MENTIONS
  -> provenance: every chunk carries document_id; every derived triple lives in
     the document's named graph; entity/relationship rows carry source_ids.

Structured CSVs from the dataset directory are loaded into the typed tables
(schema in store.structured) with the dataset itself recorded as provenance.
"""

from __future__ import annotations

import csv
import json
import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Engine

from nexusgraph.config import Settings
from nexusgraph.domain.ids import entity_uri
from nexusgraph.domain.models import Chunk, DocumentMeta, Entity, Relationship
from nexusgraph.ingestion.chunking import chunk_text
from nexusgraph.ingestion.extraction import ExtractionResult
from nexusgraph.ingestion.parsers import ParseError, parse_file, supported
from nexusgraph.ingestion.resolution import EntityResolver, dedupe_entities
from nexusgraph.observability.logging import get_logger
from nexusgraph.retrieval.embeddings import Embedder
from nexusgraph.store.documents import DocumentStore
from nexusgraph.store.graph import GraphStore
from nexusgraph.store.knowledge import EntityStore
from nexusgraph.store.structured import STRUCTURED_SCHEMA, insert_rows

logger = get_logger("ingestion")

_DATASET_SOURCE = "synthetic:seed-42"


@dataclass
class IngestionReport:
    documents: int = 0
    chunks: int = 0
    entities: int = 0
    relationships: int = 0
    merged_duplicates: int = 0
    mention_triples: int = 0
    structured_rows: int = 0
    skipped_files: list[str] = field(default_factory=list)
    extraction_methods: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"ingested: {self.documents} documents ({self.chunks} chunks), "
            f"{self.entities} entities, {self.relationships} relationships, "
            f"{self.mention_triples} mention triples, "
            f"{self.structured_rows} structured rows; "
            f"duplicates merged: {self.merged_duplicates}; "
            f"skipped: {len(self.skipped_files)}"
        )


class IngestionPipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        engine: Engine,
        graph_store: GraphStore,
        entity_store: EntityStore,
        document_store: DocumentStore,
        embedder: Embedder,
        extractor_factory: Callable[[object], object],
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._graph = graph_store
        self._entities = entity_store
        self._documents = document_store
        self._embedder = embedder
        self._extractor_factory = extractor_factory

    # ------------------------------------------------------------------ full
    def ingest_dataset(self, dataset_dir: pathlib.Path,
                       ontology_path: pathlib.Path) -> IngestionReport:
        report = IngestionReport()
        self._graph.load_ontology(ontology_path)
        data_graph = dataset_dir / "graph.ttl"
        if data_graph.exists():
            self._graph.load_data(data_graph)

        report.structured_rows += self._load_structured(dataset_dir / "tables")
        report.entities, report.relationships, report.merged_duplicates = \
            self._load_entities(dataset_dir / "entities.csv",
                                dataset_dir / "relationships.csv")

        aliases_path = dataset_dir / "aliases.json"
        aliases: dict[str, str] = {}
        if aliases_path.exists():
            aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
        resolver = EntityResolver(aliases)
        for entity in self._entities.find_entities(limit=10_000):
            resolver.add(entity.name, entity.id)

        extractor = self._extractor_factory(resolver)
        doc_meta = self._load_sidecar_metadata(dataset_dir / "documents_index.json")
        report.documents, report.chunks, report.mention_triples = self._ingest_documents(
            dataset_dir / "documents", resolver, extractor, doc_meta, report)
        return report

    @staticmethod
    def _load_sidecar_metadata(index_path: pathlib.Path) -> dict[str, dict[str, str]]:
        """Optional generator sidecar (filename -> title/document_date)."""
        if not index_path.exists():
            return {}
        try:
            entries = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {entry["filename"]: {
            "title": entry.get("title") or "",
            "document_date": entry.get("document_date") or "",
            "doc_id": entry.get("doc_id") or "",
        } for entry in entries if entry.get("filename")}

    # -------------------------------------------------------------- structured
    def _load_structured(self, tables_dir: pathlib.Path) -> int:
        """Load CSV tables; tables are cleared first so ingestion is idempotent."""
        from sqlalchemy import MetaData as sa_MetaData
        from sqlalchemy import delete as sa_delete

        rows_loaded = 0
        if not tables_dir.exists():
            return 0
        md = sa_MetaData()
        md.reflect(bind=self._engine, only=list(STRUCTURED_SCHEMA))
        with self._engine.begin() as conn:
            for table_obj in md.sorted_tables:
                conn.execute(sa_delete(table_obj))
        for table_name in sorted(STRUCTURED_SCHEMA):
            path = tables_dir / f"{table_name}.csv"
            if not path.exists():
                continue
            with path.open(encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            rows_loaded += insert_rows(self._engine, table_name, rows)
        return rows_loaded

    # ---------------------------------------------------------------- entities
    def _load_entities(self, entities_csv: pathlib.Path,
                       relationships_csv: pathlib.Path) -> tuple[int, int, int]:
        entities: list[Entity] = []
        with entities_csv.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                entities.append(Entity(
                    id=row["id"], type=row["type"], name=row["name"],
                    description=row["description"] or None,
                    source_ids=[_DATASET_SOURCE],
                ))
        entities, merges = dedupe_entities(entities)
        self._entities.upsert_entities(entities)

        relationships: list[Relationship] = []
        with relationships_csv.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                relationships.append(Relationship(
                    source_id=row["source_id"], target_id=row["target_id"],
                    relation=row["relation"], source_ids=[_DATASET_SOURCE],
                ))
        self._entities.upsert_relationships(relationships)
        return len(entities), len(relationships), len(merges)

    # --------------------------------------------------------------- documents
    def _ingest_documents(
        self,
        documents_dir: pathlib.Path,
        resolver: EntityResolver,
        extractor: object,
        doc_meta: dict[str, dict[str, str]],
        report: IngestionReport,
    ) -> tuple[int, int, int]:
        if not documents_dir.exists():
            return 0, 0, 0
        doc_count = chunk_count = mention_count = 0
        for path in sorted(documents_dir.iterdir()):
            if path.is_dir() or not supported(path.suffix):
                if path.is_file():
                    report.skipped_files.append(path.name)
                continue
            try:
                text, content_type, meta = parse_file(path)
            except (ParseError, UnicodeDecodeError) as exc:
                logger.warning("skipping %s: %s", path.name, exc)
                report.skipped_files.append(path.name)
                continue

            sidecar = doc_meta.get(path.name, {})
            doc_id = sidecar.get("doc_id") or f"doc:{path.stem}"
            title = sidecar.get("title") or _extract_title(text, path.stem)
            document_date = sidecar.get("document_date") or None
            result: ExtractionResult = extractor.extract(text)  # type: ignore[attr-defined]
            report.extraction_methods[doc_id] = result.method

            chunks = chunk_text(text, self._settings.limits.max_chunk_chars)
            embeddings = self._embedder.embed_texts(chunks)
            chunk_models = [
                Chunk(
                    id=f"{doc_id}#chunk-{ordinal:04d}",
                    document_id=doc_id,
                    ordinal=ordinal,
                    text=chunk,
                    entity_ids=result.entity_ids,
                    metadata={"provenance": {"source_id": doc_id,
                                             "location": f"{doc_id}#chunk-{ordinal:04d}"}},
                    embedding=embedding,
                )
                for ordinal, (chunk, embedding) in enumerate(zip(chunks, embeddings,
                                                                 strict=True), start=1)
            ]

            self._documents.upsert_document(DocumentMeta(
                id=doc_id, title=title, content_type=content_type,
                source_path=str(path), text=text,
                metadata={
                    **meta,
                    "document_id": doc_id,
                    "mentions": result.entity_ids,
                    "extraction_method": result.method,
                    "provenance": {"source_id": _DATASET_SOURCE, "location": str(path)},
                },
            ))
            self._documents.replace_chunks(doc_id, chunk_models)

            uris = [entity_uri(*e.split(":", 1)) for e in result.entity_ids
                    if ":" in e]
            self._graph.add_document_entity(
                doc_id, title, content_type, document_date, uris)
            doc_count += 1
            chunk_count += len(chunk_models)
            mention_count += len(uris)
        return doc_count, chunk_count, mention_count


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines()[:8]:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped and not stripped.startswith(">") and not stripped.startswith("["):
            return stripped[:120]
    return fallback
