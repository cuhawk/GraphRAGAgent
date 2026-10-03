"""Paragraph-aware chunking with hard-split fallback for oversized paragraphs."""

from __future__ import annotations

import re

_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, max_chars: int = 1_200) -> list[str]:
    """Split text into chunks of at most ``max_chars`` characters.

    Strategy: merge whole paragraphs while they fit; oversized paragraphs are
    split on sentence boundaries, then on word boundaries as a last resort.
    """
    if not text.strip():
        return []
    chunks: list[str] = []
    buffer = ""

    for raw_paragraph in _PARAGRAPH_RE.split(text):
        paragraph = raw_paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.extend(_hard_split(paragraph, max_chars))
            continue
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            if buffer:
                chunks.append(buffer)
            buffer = paragraph
    if buffer:
        chunks.append(buffer)
    return chunks


def _hard_split(paragraph: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    for sentence in _SENTENCE_RE.split(paragraph):
        if len(sentence) <= max_chars:
            pieces.append(sentence)
            continue
        words = sentence.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) > max_chars and current:
                pieces.append(current)
                current = word[:max_chars]
            else:
                current = candidate
        if current:
            pieces.append(current)
    # Re-merge small pieces greedily.
    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1]) + len(piece) + 1 <= max_chars:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return merged
