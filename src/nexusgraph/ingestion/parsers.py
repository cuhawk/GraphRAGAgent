"""Document parsers: CSV, JSON, Markdown, plain text, PDF (text layer via pypdf)."""

from __future__ import annotations

import json
import pathlib

from nexusgraph.observability.logging import get_logger

logger = get_logger("ingestion.parsers")

CONTENT_TYPES: dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".pdf": "application/pdf",
}

MAX_FILE_BYTES = 20_000_000


class ParseError(ValueError):
    pass


def supported(suffix: str) -> bool:
    return suffix.lower() in CONTENT_TYPES


def parse_file(path: pathlib.Path) -> tuple[str, str, dict]:
    """Return ``(text, content_type, metadata)`` for a document file."""
    suffix = path.suffix.lower()
    content_type = CONTENT_TYPES.get(suffix)
    if content_type is None:
        raise ParseError(f"unsupported file type: {suffix}")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ParseError(f"file too large: {path.name} ({len(raw)} bytes)")

    metadata: dict = {}
    if suffix == ".pdf":
        text = _parse_pdf(raw)
        metadata["parser"] = "pypdf"
    elif suffix == ".json":
        text = _parse_json(raw)
        metadata["parser"] = "json"
    elif suffix == ".csv":
        text = raw.decode("utf-8-sig")
        metadata["parser"] = "csv"
    else:
        text = raw.decode("utf-8-sig")
        metadata["parser"] = "text"

    metadata["file_name"] = path.name
    metadata["file_size_bytes"] = len(raw)
    return text, content_type, metadata


def _parse_pdf(raw: bytes) -> str:
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise ParseError(f"PDF parsing failed: {exc}") from exc
    return "\n\n".join(p for p in pages if p.strip())


def _parse_json(raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc}") from exc
    # Keep a readable, deterministic textual projection for chunking/extraction.
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
