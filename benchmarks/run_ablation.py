"""Measure retrieval and answer quality on the offline diagnostic suite."""

from __future__ import annotations

import argparse
from collections import defaultdict
from math import log2
from pathlib import Path
from statistics import fmean
from tempfile import TemporaryDirectory

from evals.cases import CASES, EvalCase
from evals.graders import contains_anchors, directive_reached, grade
from evals.runtime import diagnostic_runtime

from nexusgraph.agent.orchestrator import AgentOrchestrator
from nexusgraph.domain.models import AgentAnswer, SearchHit
from nexusgraph.retrieval.context import content_terms
from nexusgraph.retrieval.service import RetrievalMode, RetrievalService
from nexusgraph.runtime import Runtime

MODES: tuple[tuple[str, RetrievalMode], ...] = (
    ("Dense-only", "dense"),
    ("Hybrid RRF", "rrf"),
    ("Hybrid RRF + Reranker", "rerank"),
)

METHODOLOGY = """# Retrieval ablation

Run with `uv run python -m benchmarks.run_ablation --results benchmarks/RESULTS.md`.

The offline suite uses the seed-42 synthetic corpus plus the operational
records in `evals/diagnostic.py`. Every mode uses the same corpus, 256-dimensional
hash embeddings, candidate depth, context budget, planner and synthesizer.

Ranking uses unique document IDs from the raw ranking and only queries with
authored relevance labels. The answer stage runs all cases. Citation precision
counts emitted document claim-to-source links with a verbatim span at the stored
location, a relevant document ID and, where annotated, an answer anchor in the
span. The packed baseline counts relevant, source-verified passages in the
same candidates before synthesis, using the Wave 5 packer coverage rule. It
measures candidate quality on this corpus. The answer and packed columns count
different units, so both denominators are shown.

Refusal accuracy uses the unanswerable category. The packed baseline uses the
absence of packed retrieval hits. Answer coverage measures how often the agent
answers labeled answerable document questions. Answer pass rate also requires
the expected anchors and sources. Hygiene pass rate requires the directive
to reach the context packer and its canary to stay out of the answer and
returned evidence. These measurements characterize the offline configuration.
The thresholds were developed with this diagnostic suite, so the results
are development measurements on a synthetic corpus.
"""


def ranking_metrics(ranked: list[str], relevant: set[str]) -> tuple[float, float, float]:
    unique = list(dict.fromkeys(ranked))
    hits = [i for i, doc in enumerate(unique[:10], 1) if doc in relevant]
    ideal_dcg = sum(1 / log2(i + 1) for i in range(1, min(len(relevant), 10) + 1))
    return (
        1 / hits[0] if hits else 0.0,
        len(relevant.intersection(unique[:5])) / len(relevant),
        sum(1 / log2(i + 1) for i in hits) / ideal_dcg,
    )


def _legacy_candidates(case: EvalCase, ranked: list[SearchHit]) -> list[SearchHit]:
    identifiers = {term for term in content_terms(case.question) if any(c.isdigit() for c in term)}
    if not identifiers:
        return ranked
    return [hit for hit in ranked if identifiers & content_terms(hit.text)]


def _verified_passage(runtime: Runtime, hit: SearchHit) -> bool:
    stored = runtime.documents.get_chunk(hit.chunk_id)
    return bool(
        stored
        and stored.document_id == hit.document_id
        and hit.citation
        and stored.metadata.get("provenance", {}).get("location") == hit.citation
        and hit.source_text == stored.text
    )


def _citation_counts(
    case: EvalCase, runtime: Runtime, hits: list[SearchHit], answer: AgentAnswer
) -> tuple[int, int]:
    gold = set(case.expected.expected_document_ids)
    by_location = {(hit.document_id, hit.citation): hit for hit in hits}
    sources = {item.evidence_id: item for item in answer.evidence}
    correct = emitted = 0
    for claim in answer.claims:
        for eid in claim.evidence_ids:
            evidence = sources[eid]
            if evidence.source_type != "document":
                continue
            emitted += 1
            hit = by_location.get((evidence.source_id, evidence.location))
            span = claim.supporting_spans.get(eid, "")
            correct += bool(
                hit
                and hit.document_id in gold
                and _verified_passage(runtime, hit)
                and span
                and span in (hit.source_text or "")
                and contains_anchors(
                    span, case.expected.document_anchors.get(evidence.source_id, ())
                )
            )
    return correct, emitted


def _ratio(correct: int, total: int) -> str:
    return f"{correct / total:.4f} ({correct}/{total})" if total else "—"


def _row(*cells: str) -> str:
    return "| " + " | ".join(cells) + " |"


def run(data_dir: Path) -> str:
    runtime = diagnostic_runtime(data_dir)
    ranking_rows = [
        _row("Configuration", "Queries", "MRR@10", "Recall@5", "NDCG@10"),
        _row("---", "---:", "---:", "---:", "---:"),
    ]
    slice_rows = [
        _row("Configuration", "Category", "Queries", "MRR@10", "Recall@5", "NDCG@10"),
        _row("---", "---", "---:", "---:", "---:", "---:"),
    ]
    quality_rows = [
        _row(
            "Configuration",
            "Packed precision",
            "Citation precision",
            "Packed refusal",
            "Refusal accuracy",
            "Answer coverage",
            "Answer pass rate",
            "Hygiene pass rate",
        ),
        _row("---", "---:", "---:", "---:", "---:", "---:", "---:", "---:"),
    ]
    try:
        for label, mode in MODES:
            retrieval = RetrievalService(
                runtime.documents,
                runtime.vector_index,
                runtime.embedder,
                runtime.limits,
                default_mode=mode,
            )
            runtime.retrieval = retrieval
            agent = AgentOrchestrator(runtime)
            ranking: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
            legacy_refusals = refusals = unanswerable = 0
            packed_correct = packed_total = cited_correct = cited_total = 0
            answered = answer_pass = answerable = hygiene_pass = hygiene = 0
            k = runtime.limits.retrieval_k
            for case in CASES:
                ranked = retrieval.rank(case.question, depth=max(40, k * 4), mode=mode)
                baseline = retrieval.pack(_legacy_candidates(case, ranked), k=k)
                packed = retrieval.pack(ranked, k=k)
                gold = set(case.expected.expected_document_ids)
                answer = agent.run(case.question)
                if gold:
                    ranking[case.category].append(
                        ranking_metrics(
                            [hit.document_id for hit in ranked],
                            gold,
                        )
                    )
                    packed_total += len(baseline.hits)
                    packed_correct += sum(
                        hit.document_id in gold and _verified_passage(runtime, hit)
                        for hit in baseline.hits
                    )
                    correct, emitted = _citation_counts(case, runtime, ranked, answer)
                    cited_correct += correct
                    cited_total += emitted
                    answerable += 1
                    answered += not answer.insufficient
                    answer_pass += grade(case, answer).passed
                if case.category == "unanswerable":
                    unanswerable += 1
                    legacy_refusals += baseline.abstained
                    refusals += answer.insufficient
                if case.expected.injection_document_id:
                    hygiene += 1
                    reached = directive_reached(case, packed.hits)
                    hygiene_pass += grade(case, answer, injection_reached=reached).passed
            overall = [metrics for group in ranking.values() for metrics in group]
            ranking_rows.append(_row(label, *_ranking_cells(overall)))
            slice_rows.extend(
                _row(label, category, *_ranking_cells(metrics))
                for category, metrics in ranking.items()
            )
            quality_rows.append(
                _row(
                    label,
                    _ratio(packed_correct, packed_total),
                    _ratio(cited_correct, cited_total),
                    _ratio(legacy_refusals, unanswerable),
                    _ratio(refusals, unanswerable),
                    _ratio(answered, answerable),
                    _ratio(answer_pass, answerable),
                    _ratio(hygiene_pass, hygiene),
                )
            )
    finally:
        runtime.engine.dispose()
    return "\n".join(
        [
            f"## Overall ranking ({len(CASES)} total diagnostic queries)",
            "",
            *ranking_rows,
            "",
            "## Ranking by category",
            "",
            *slice_rows,
            "",
            "## Answer quality and packed baseline",
            "",
            *quality_rows,
        ]
    )


def _ranking_cells(metrics: list[tuple[float, float, float]]) -> list[str]:
    return [str(len(metrics)), *(f"{fmean(column):.4f}" for column in zip(*metrics, strict=True))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, help="write the measured Markdown report")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="nexusgraph-ablation-") as tmpdir:
        table = run(Path(tmpdir))
    print(table)
    if args.results:
        args.results.write_text(f"{METHODOLOGY}\n{table}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
