"""Evidence scoring and deterministic context packing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from math import sqrt

from nexusgraph.domain.models import SearchHit
from nexusgraph.retrieval.bm25 import tokenize

_STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "at",
        "about",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "many",
        "me",
        "of",
        "on",
        "or",
        "say",
        "so",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)
_CONTEXT_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def context_token_count(text: str) -> int:
    """Count word runs and punctuation using the offline context tokenizer."""
    return len(_CONTEXT_TOKEN.findall(text))


@lru_cache(maxsize=8192)
def _trigrams(term: str) -> frozenset[str]:
    padded = f"^{term}$"
    return frozenset(padded[i : i + 3] for i in range(len(term)))


def content_terms(text: str) -> set[str]:
    return set(tokenize(text)) - _STOP_WORDS


def interaction(query: str, text: str) -> tuple[float, float]:
    """MaxSim-style token interaction with exact matching for technical identifiers."""
    query_terms = content_terms(query)
    terms = content_terms(text)
    technical = {term for term in query_terms if any(char.isdigit() for char in term)}
    if not query_terms:
        return 0.0, 0.0

    def similarity(term: str) -> float:
        if term in terms:
            return 1.0
        if term in technical or len(term) < 4:
            return 0.0
        grams = _trigrams(term)
        best = 0.0
        for other in terms:
            if len(other) < 4:
                continue
            other_grams = _trigrams(other)
            best = max(best, len(grams & other_grams) / sqrt(len(grams) * len(other_grams)))
        return best

    similarities = [similarity(term) for term in sorted(query_terms)]
    score = sum(similarities) / len(similarities)
    coverage = sum(value >= 0.60 for value in similarities) / len(similarities)
    if technical and not technical <= terms:
        score *= 0.5
        if not technical & terms:
            coverage = 0.0
    return score, coverage


@dataclass(frozen=True)
class PackedContext:
    hits: tuple[SearchHit, ...]
    text: str
    token_count: int

    @property
    def abstained(self) -> bool:
        return not self.hits


def pack_context(
    hits: list[SearchHit],
    *,
    k: int,
    token_budget: int,
    char_budget: int,
    min_coverage: float,
) -> PackedContext:
    """Keep complete, cited passages that fit both budgets in ranked order."""
    kept: list[SearchHit] = []
    entries: list[str] = []
    seen: set[str] = set()
    tokens = chars = 0
    for hit in hits:
        if len(kept) >= k:
            break
        if hit.evidence_coverage < min_coverage:
            continue
        citation = hit.citation or hit.chunk_id
        if citation in seen:
            continue
        entry = f"{citation}\n{hit.text}"
        cost = context_token_count(entry)
        length = len(entry) + (2 if entries else 0)
        if tokens + cost > token_budget or chars + length > char_budget:
            continue
        kept.append(hit)
        entries.append(entry)
        seen.add(citation)
        tokens += cost
        chars += length
    return PackedContext(tuple(kept), "\n\n".join(entries), tokens)
