"""Composition root: builds the object graph once, used by API/CLI/MCP/evals.

Two storage profiles (``local`` / ``postgres``) differ only in configuration;
the components are identical.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine

from nexusgraph.config import LimitsSettings, Settings
from nexusgraph.db.engine import create_engine_for, init_schema
from nexusgraph.ingestion.pipeline import IngestionPipeline, IngestionReport
from nexusgraph.observability.logging import get_logger
from nexusgraph.observability.tracing import Tracer, TraceSink
from nexusgraph.retrieval.embeddings import Embedder, make_embedder
from nexusgraph.retrieval.service import RetrievalService
from nexusgraph.store.cache import make_cache
from nexusgraph.store.documents import DocumentStore
from nexusgraph.store.graph import GraphStore
from nexusgraph.store.knowledge import EntityStore
from nexusgraph.store.traces import TraceSqlSink
from nexusgraph.store.vector import VectorIndex, make_vector_index

logger = get_logger("runtime")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ONTOLOGY_PATH = _REPO_ROOT / "ontology" / "nexusgraph.ttl"
DEFAULT_SEED = 42


@dataclass
class Runtime:
    settings: Settings
    engine: Engine
    graph: GraphStore
    entities: EntityStore
    documents: DocumentStore
    vector_index: VectorIndex
    embedder: Embedder
    retrieval: RetrievalService
    trace_sink: TraceSink
    tracer: Tracer
    cache: object
    ontology_path: pathlib.Path
    dataset_dir: pathlib.Path

    @property
    def limits(self) -> LimitsSettings:
        return self.settings.limits

    def is_bootstrapped(self) -> bool:
        return self.entities.count() > 0 and self.documents.document_count() > 0

    def refresh_vector_index(self) -> int:
        return self.vector_index.refresh()


def build_runtime(settings: Settings) -> Runtime:
    settings.ensure_dirs()
    engine = create_engine_for(settings)
    init_schema(engine, settings)

    graph = GraphStore(settings.resolved_rdf_store_path)
    entities = EntityStore(engine)
    documents = DocumentStore(engine)
    vector_index = make_vector_index(engine, settings.profile)
    embedder = make_embedder(settings.llm)
    cache = make_cache(settings.redis_url)
    retrieval = RetrievalService(documents, vector_index, embedder, settings.limits)
    trace_sink = TraceSqlSink(engine)
    tracer = Tracer(otlp_endpoint=settings.otlp_endpoint)

    return Runtime(
        settings=settings,
        engine=engine,
        graph=graph,
        entities=entities,
        documents=documents,
        vector_index=vector_index,
        embedder=embedder,
        retrieval=retrieval,
        trace_sink=trace_sink,
        tracer=tracer,
        cache=cache,
        ontology_path=ONTOLOGY_PATH,
        dataset_dir=settings.data_dir / "dataset",
    )


def make_extractor(runtime: Runtime) -> Callable[..., object]:
    """Extraction factory honouring the configured LLM provider."""
    if runtime.settings.llm.provider == "openai-compatible":
        from nexusgraph.ingestion.extraction import LLMAssistedExtractor
        from nexusgraph.ingestion.resolution import EntityResolver

        def factory_llm(resolver: EntityResolver) -> LLMAssistedExtractor:
            from nexusgraph.llm.base import make_llm_client

            return LLMAssistedExtractor(
                make_llm_client(runtime.settings.llm),
                resolver,
                runtime.settings.llm,
                runtime.settings.limits.max_input_chars,
            )

        return factory_llm

    from nexusgraph.ingestion.extraction import DeterministicExtractor

    return DeterministicExtractor


def generate_dataset(settings: Settings, seed: int = DEFAULT_SEED) -> dict:
    """Materialise the synthetic corpus into ``settings.data_dir/dataset``."""
    from nexusgraph.synth import generate_dataset

    settings.ensure_dirs()
    out_dir = settings.data_dir / "dataset"
    manifest = generate_dataset(out_dir, seed)
    logger.info("synthetic dataset generated at %s (seed=%s)", out_dir, seed)
    return manifest


def bootstrap(
    settings: Settings, seed: int = DEFAULT_SEED, regenerate: bool = True
) -> IngestionReport:
    """Generate + ingest the synthetic dataset; the one-command setup path."""
    if regenerate:
        import shutil

        # A regenerated dataset must not leave stale triples behind: the RDF
        # store is additive, so rebuild it from scratch.
        shutil.rmtree(settings.resolved_rdf_store_path, ignore_errors=True)
    runtime = build_runtime(settings)
    try:
        if regenerate or not (runtime.dataset_dir / "manifest.json").exists():
            generate_dataset(settings, seed)
        pipeline = IngestionPipeline(
            settings=settings,
            engine=runtime.engine,
            graph_store=runtime.graph,
            entity_store=runtime.entities,
            document_store=runtime.documents,
            embedder=runtime.embedder,
            extractor_factory=make_extractor(runtime),
        )
        report = pipeline.ingest_dataset(runtime.dataset_dir, runtime.ontology_path)
        runtime.refresh_vector_index()
        logger.info("bootstrap complete: %s", report.summary())
        return report
    finally:
        runtime.engine.dispose()


def ensure_bootstrapped(settings: Settings) -> tuple[Runtime, bool]:
    """Build a runtime and bootstrap the data if the stores are empty.

    Returns ``(runtime, bootstrapped_now)``.
    """
    runtime = build_runtime(settings)
    if settings.bootstrap_on_start and not runtime.is_bootstrapped():
        dataset_manifest = runtime.dataset_dir / "manifest.json"
        pipeline = IngestionPipeline(
            settings=settings,
            engine=runtime.engine,
            graph_store=runtime.graph,
            entity_store=runtime.entities,
            document_store=runtime.documents,
            embedder=runtime.embedder,
            extractor_factory=make_extractor(runtime),
        )
        if not dataset_manifest.exists():
            generate_dataset(settings)
        pipeline.ingest_dataset(runtime.dataset_dir, runtime.ontology_path)
        runtime.refresh_vector_index()
        return runtime, True
    return runtime, False
