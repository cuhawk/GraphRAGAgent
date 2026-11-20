"""Run the retrieval ablation on the seed-42 eval corpus."""

from __future__ import annotations

import argparse
import re
from math import log2
from pathlib import Path
from statistics import fmean
from tempfile import TemporaryDirectory

from evals.cases import CASES

from nexusgraph.config import Settings
from nexusgraph.retrieval.service import RetrievalMode
from nexusgraph.runtime import ensure_bootstrapped

MODES: tuple[tuple[str, RetrievalMode], ...] = (
    ("Dense-only", "dense"),
    ("Hybrid RRF", "rrf"),
    ("Hybrid RRF + Reranker", "rerank"),
)
CITATION = re.compile(r"\[([^:\]\s]+):([^:\]\s]+):([1-9]\d*)\]")


def ranking_metrics(ranked: list[str], relevant: set[str]) -> tuple[float, float, float]:
    unique = list(dict.fromkeys(ranked))
    hits = [i for i, doc in enumerate(unique[:10], 1) if doc in relevant]
    ideal_dcg = sum(1 / log2(i + 1) for i in range(1, min(len(relevant), 10) + 1))
    return (
        1 / hits[0] if hits else 0.0,
        len(relevant.intersection(unique[:5])) / len(relevant),
        sum(1 / log2(i + 1) for i in hits) / ideal_dcg,
    )


def run(data_dir: Path) -> str:
    # Explicit settings isolate the benchmark from local profile/model overrides.
    settings = Settings(
        _env_file=None,
        profile="local",
        data_dir=data_dir,
        bootstrap_on_start=True,
        database_url=None,
        redis_url=None,
        rdf_store_path=None,
        llm={"provider": "mock", "embedding_provider": "hash", "embedding_dim": 256},
        limits={},
    )
    runtime, _ = ensure_bootstrapped(settings)
    rows = [
        "| Configuration | MRR@10 | Recall@5 | NDCG@10 | Citation precision | Refusal accuracy |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    try:
        for label, mode in MODES:
            ranking: list[tuple[float, float, float]] = []
            refusals: list[bool] = []
            correct = emitted = 0
            for case in CASES:
                ranked = runtime.retrieval.rank(case.question, depth=40, mode=mode)
                packed = runtime.retrieval.pack(ranked, k=runtime.limits.retrieval_k)
                gold = set(case.expected.expected_document_ids)
                if gold:
                    ranking.append(ranking_metrics([hit.document_id for hit in ranked], gold))
                    citations = [
                        (hit, runtime.documents.get_chunk(hit.chunk_id)) for hit in packed.hits
                    ]
                    emitted += len(citations)
                    correct += sum(
                        hit.document_id in gold
                        and hit.citation is not None
                        and CITATION.fullmatch(hit.citation) is not None
                        and stored is not None
                        and stored.document_id == hit.document_id
                        and stored.metadata.get("provenance", {}).get("location") == hit.citation
                        and hit.text.endswith(stored.text)
                        for hit, stored in citations
                    )
                if case.category == "unanswerable":
                    refusals.append(packed.abstained)
            means = [fmean(metric) for metric in zip(*ranking, strict=True)]
            values = [*means, correct / emitted if emitted else 0.0, fmean(refusals)]
            rows.append(f"| {label} | " + " | ".join(f"{value:.4f}" for value in values) + " |")
    finally:
        runtime.engine.dispose()
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, help="write the measured Markdown report")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="nexusgraph-ablation-") as tmpdir:
        table = run(Path(tmpdir))
    print(table)
    if args.results:
        args.results.write_text(
            "# Retrieval ablation\n\n"
            "Run with `uv run python -m benchmarks.run_ablation` to print the measured table.\n\n"
            "All eval questions ran against a fresh seed-42 corpus with offline hash embeddings. "
            "Ranking metrics use unique document IDs and cases with document relevance labels. "
            "Citation precision is the fraction of packed citations with a matching stored "
            "source and a gold document ID on those same cases. "
            "Refusal accuracy is measured on the unanswerable cases. "
            "All configurations share the evidence gate and context budgets.\n\n"
            f"{table}\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
