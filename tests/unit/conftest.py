"""Shared store fixtures used by storage, tool and agent tests."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import Engine

from nexusgraph.config import LimitsSettings, Settings
from nexusgraph.db.engine import create_engine_for, init_schema
from nexusgraph.store.documents import DocumentStore
from nexusgraph.store.knowledge import EntityStore
from nexusgraph.store.structured import STRUCTURED_SCHEMA, create_structured_tables


@pytest.fixture()
def limits() -> LimitsSettings:
    return LimitsSettings()


@pytest.fixture()
def engine(tmp_path: Path) -> Iterator[Engine]:
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path}/test.db",
                        _env_file=None)
    eng = create_engine_for(settings)
    init_schema(eng, settings)
    yield eng
    eng.dispose()


@pytest.fixture()
def seeded_engine(engine, tmp_path: Path) -> Engine:
    """Engine with the synthetic dataset's structured tables populated."""
    from nexusgraph.synth import build_corpus
    from nexusgraph.store.structured import insert_rows

    corpus = build_corpus()
    for table in STRUCTURED_SCHEMA:
        rows = corpus.tables.get(table)
        if rows:
            insert_rows(engine, table, rows)
    return engine


@pytest.fixture()
def document_store(engine) -> DocumentStore:
    return DocumentStore(engine)


@pytest.fixture()
def entity_store(engine) -> EntityStore:
    return EntityStore(engine)


@pytest.fixture()
def graph_store(tmp_path: Path):
    """GraphStore loaded with ontology + generated data graph."""
    from nexusgraph.store.graph import GraphStore
    from nexusgraph.synth import build_corpus
    from nexusgraph.synth.rdf import build_data_graph, write_turtle

    ontology_path = Path(__file__).parents[2] / "ontology" / "nexusgraph.ttl"
    data_path = tmp_path / "graph.ttl"
    write_turtle(build_data_graph(build_corpus()), data_path)

    store = GraphStore(":memory:")
    store.load_ontology(ontology_path)
    store.load_data(data_path)
    assert store.count() > 500
    return store


@pytest.fixture()
def structured_tables(engine):
    create_structured_tables(engine)
    return STRUCTURED_SCHEMA
