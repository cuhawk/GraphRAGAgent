"""Compact Okapi BM25 (k1=1.5, b=0.75) used to rerank dense retrieval candidates.

Documented approximation: IDF statistics are computed over the candidate set
(not the whole corpus) because this ranker only ever sees the top dense
candidates. Deterministic and dependency-free.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

_TOKEN_RE = re.compile(r"[a-z0-9]+")

K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def bm25_scores(query: str, documents: Sequence[str]) -> list[float]:
    if not documents:
        return []
    query_terms = tokenize(query)
    if not query_terms:
        return [0.0] * len(documents)

    doc_tokens = [tokenize(doc) for doc in documents]
    doc_len = [len(tokens) for tokens in doc_tokens]
    avg_len = sum(doc_len) / len(documents) if documents else 1.0

    df: dict[str, int] = {}
    for tokens in doc_tokens:
        for term in set(tokens):
            df[term] = df.get(term, 0) + 1

    scores = [0.0] * len(documents)
    for i, tokens in enumerate(doc_tokens):
        tf: dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        score = 0.0
        for term in query_terms:
            if term not in tf:
                continue
            idf = math.log(1.0 + (len(documents) - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (K1 + 1.0) / (
                tf[term] + K1 * (1.0 - B + B * doc_len[i] / max(avg_len, 1.0)))
        scores[i] = score

    max_score = max(scores, default=0.0)
    if max_score > 0:
        scores = [s / max_score for s in scores]
    return scores
