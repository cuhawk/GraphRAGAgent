"""Ingestion subsystem: parse, chunk, extract, resolve, embed, index, prove."""

from nexusgraph.ingestion.chunking import chunk_text
from nexusgraph.ingestion.extraction import DeterministicExtractor, LLMAssistedExtractor
from nexusgraph.ingestion.pipeline import IngestionPipeline, IngestionReport
from nexusgraph.ingestion.parsers import ParseError, parse_file
from nexusgraph.ingestion.resolution import EntityResolver, dedupe_entities, normalize_name

__all__ = [
    "DeterministicExtractor",
    "EntityResolver",
    "IngestionPipeline",
    "IngestionReport",
    "LLMAssistedExtractor",
    "ParseError",
    "chunk_text",
    "dedupe_entities",
    "normalize_name",
    "parse_file",
]
