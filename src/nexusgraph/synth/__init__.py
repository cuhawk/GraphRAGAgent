"""Synthetic dataset generation (fixed seed, fully reproducible)."""

from __future__ import annotations

import pathlib

import pyoxigraph as ox

from nexusgraph.synth.documents import build_documents, render_pdf
from nexusgraph.synth.generator import (
    Corpus,
    EntityRec,
    GeneratedDocument,
    build_corpus,
    write_corpus,
)
from nexusgraph.synth.rdf import build_data_graph, write_turtle

__all__ = [
    "Corpus",
    "EntityRec",
    "GeneratedDocument",
    "build_corpus",
    "build_data_graph",
    "build_documents",
    "generate_dataset",
    "render_pdf",
    "write_corpus",
    "write_turtle",
]


def generate_dataset(out_dir: pathlib.Path, seed: int = 42) -> dict[str, object]:
    """Generate the full synthetic corpus into ``out_dir``; returns the manifest."""
    corpus = build_corpus(seed)
    return write_corpus(corpus, out_dir)


def graph_store(corpus: Corpus) -> ox.Store:
    """In-memory RDF store for the entity/relationship graph (no documents)."""
    return build_data_graph(corpus)
