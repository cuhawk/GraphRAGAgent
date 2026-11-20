"""Paragraph-aware chunking with hard-split fallback for oversized paragraphs."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag
from markdown_it import MarkdownIt

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


@dataclass(frozen=True)
class Passage:
    text: str
    headings: tuple[str, ...]
    start_line: int
    end_line: int

    @property
    def contextual_text(self) -> str:
        return f"{' > '.join(self.headings)}\n\n{self.text}" if self.headings else self.text


def _table_parts(
    header: str, rows: Iterable[tuple[int, int, str]], budget: int, footer: str = ""
) -> Iterator[tuple[int, int, str]]:
    """Repeat headers on continuation chunks and keep every row atomic."""
    body = ""
    start = end = 0
    for first, last, row in rows:
        if body and len(header) + len(body) + len(row) + len(footer) > budget:
            yield start, end, header + body + footer
            body = ""
        if not body:
            start = first
        body += row
        end = last
    if body or header:
        yield start, end, header + body + footer


def _html_blocks(text: str, budget: int) -> Iterator[tuple[int, int, int, str]]:
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.select("script, style, template, head"):
        tag.decompose()

    def walk(node: Tag, line: int) -> Iterator[tuple[int, int, int, str]]:
        first = node.sourceline or line
        name = node.name
        if re.fullmatch(r"h[1-6]", name):
            yield first, first, int(name[1]), node.get_text(" ", strip=True)
        elif name == "table":
            rows = node.find_all("tr")
            # Spans and nested tables depend on surrounding rows. Keep those tables intact.
            if node.select_one("[rowspan], table") or not rows:
                yield first, first + str(node).count("\n"), 0, str(node)
                return
            headers: list[Tag] = []
            for index, row in enumerate(rows):
                if row.find_parent("thead") or (
                    len(headers) == index and row.find("th") and not row.find("td")
                ):
                    headers.append(row)
            caption = node.find("caption", recursive=False)
            prefix = "<table>" + (str(caption) if caption else "") + "".join(map(str, headers))
            header_ids = {id(row) for row in headers}
            body = (
                (
                    row.sourceline or first,
                    (row.sourceline or first) + str(row).count("\n"),
                    "\n" + str(row),
                )
                for row in rows
                if id(row) not in header_ids
            )
            for start, end, part in _table_parts(prefix, body, budget, "</table>"):
                yield start or first, end or first, 0, part
        elif name in {"p", "pre", "ul", "ol", "blockquote", "dl", "figure"} and not node.select_one(
            "table, h1, h2, h3, h4, h5, h6"
        ):
            value = str(node) if name != "p" else node.get_text()
            yield first, first + str(node).count("\n"), 0, value
        else:
            if not node.find(recursive=False):
                value = node.get_text()
                if value.strip():
                    yield first, first + value.count("\n"), 0, value
                return
            # Buffer inline content so adjacent tags don't split identifiers.
            inline: list[str] = []
            inline_line = first
            for child in node.children:
                if isinstance(child, Tag) and child.name not in {
                    "a",
                    "b",
                    "br",
                    "code",
                    "em",
                    "i",
                    "small",
                    "span",
                    "strong",
                    "sub",
                    "sup",
                }:
                    if "".join(inline).strip():
                        yield inline_line, first, 0, "".join(inline)
                    inline.clear()
                    yield from walk(child, first)
                    first = child.sourceline or first
                    inline_line = first
                else:
                    inline.append(child.get_text() if isinstance(child, Tag) else str(child))
            if "".join(inline).strip():
                yield inline_line, first, 0, "".join(inline)

    yield from walk(soup.body or soup, 1)


def _markdown_blocks(text: str, budget: int) -> Iterator[tuple[int, int, int, str]]:
    lines = text.splitlines()
    end = 0
    for token in MarkdownIt().enable("table").parse(text):
        if not token.map:
            continue
        start, stop = token.map
        if start < end:
            continue
        end = stop
        if token.type == "heading_open":
            title = lines[start].strip().lstrip("#").strip()
            title = re.sub(r"\s+#+$", "", title)
            yield start + 1, stop, int(token.tag[1]), title
        elif token.type == "table_open":
            header = "\n".join(lines[start : start + 2]) + "\n"
            rows = ((i + 1, i + 1, lines[i] + "\n") for i in range(start + 2, stop))
            for first, last, value in _table_parts(header, rows, budget):
                yield first or start + 1, last or stop, 0, value.rstrip("\n")
        elif token.type == "html_block":
            for first, last, level, value in _html_blocks(token.content, budget):
                yield start + first, start + last, level, value
        else:
            yield start + 1, stop, 0, "\n".join(lines[start:stop])


def _csv_blocks(text: str, budget: int) -> Iterator[tuple[int, int, int, str]]:
    lines = text.splitlines(keepends=True)
    reader = csv.reader(io.StringIO(text, newline=""))
    if next(reader, None) is None:
        return
    header_end = reader.line_num
    header = "".join(lines[:header_end]).rstrip("\r\n") + "\n"

    def rows() -> Iterator[tuple[int, int, str]]:
        start = header_end
        for _ in reader:
            end = reader.line_num
            yield start + 1, end, "".join(lines[start:end])
            start = end

    for start, end, value in _table_parts(header, rows(), budget):
        yield start or 1, end or header_end, 0, value.rstrip("\r\n")


def chunk_document(text: str, content_type: str, max_chars: int = 1_200) -> list[Passage]:
    """Make section-local passages with one-based source lines.

    Tables, preformatted blocks and indivisible source lines may exceed the target.
    PDF line numbers refer to the extracted layout text.
    """
    if content_type == "text/html":
        blocks = _html_blocks(text, max_chars)
    elif content_type == "text/markdown":
        blocks = _markdown_blocks(text, max_chars)
    elif content_type == "text/csv":
        blocks = _csv_blocks(text, max_chars)
    else:
        blocks = ((i, i, 0, line) for i, line in enumerate(text.splitlines(), 1))

    passages: list[Passage] = []
    headings: list[tuple[int, str]] = []
    parts: list[str] = []
    start = end = size = 0
    separator = (
        "\n" if content_type in {"application/pdf", "application/json", "text/plain"} else "\n\n"
    )

    def flush() -> None:
        nonlocal size
        if parts and any(part.strip() for part in parts):
            passages.append(
                Passage(
                    separator.join(parts).strip("\r\n"),
                    tuple(title for _, title in headings),
                    start,
                    end,
                )
            )
        parts.clear()
        size = 0

    for first, last, level, value in blocks:
        if level:
            flush()
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, value))
            continue
        added = len(value) + (len(separator) if parts else 0)
        if parts and size + added > max_chars:
            flush()
            added = len(value)
        if not parts:
            start = first
        parts.append(value)
        end = last
        size += added
    flush()
    return passages
