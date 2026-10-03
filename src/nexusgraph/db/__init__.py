"""Persistence layer: engine, ORM, RDF graph store, vector index, document store."""

from nexusgraph.db.engine import create_engine_for, init_schema

__all__ = ["create_engine_for", "init_schema"]
