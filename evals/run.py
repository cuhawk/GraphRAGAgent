"""Eval runner: executes the question set against a bootstrapped runtime and
grades deterministically.

Usage::

    python -m evals.run                 # full suite
    python -m evals.run --limit 5      # first 5 cases
    python -m evals.run --cases R1,S1  # specific cases

Outputs (``evals/results/``): ``results-<timestamp>.json``,
``latest.json`` and ``report.md``. Every number in the report comes from the
recorded run; nothing is estimated or carried over from previous runs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.cases import CASES, CATEGORIES, EvalCase
from evals.graders import CaseResult, grade, grade_error
from nexusgraph.config import get_settings
from nexusgraph.observability.logging import configure_logging, get_logger
from nexusgraph.runtime import ensure_bootstrapped

logger = get_logger("evals")

_RESULTS_DIR = Path(__file__).parent / "results"


def _git_rev() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except Exception:
        return None


def run_suite(cases: list[EvalCase], out_dir: Path) -> dict[str, Any]:
    from nexusgraph.agent.orchestrator import AgentOrchestrator

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    runtime, _ = ensure_bootstrapped(settings)
    orchestrator = AgentOrchestrator(runtime)
    provider = settings.llm.provider
    model = settings.llm.model

    results: list[CaseResult] = []
    print(f"running {len(cases)} eval cases (provider={provider}, model={model}) ...")
    for index, case in enumerate(cases, start=1):
        started = time.perf_counter()
        try:
            answer = orchestrator.run(case.question)
            result = grade(case, answer)
        except Exception as exc:  # noqa: BLE001 - a crashing case is a result
            result = grade_error(case, exc)
            logger.error("case %s crashed: %s", case.id, exc)
        results.append(result)
        print(
            f"  [{index:>2}/{len(cases)}] {case.id:<4} "
            f"{case.category:<12} {'PASS' if result.passed else 'FAIL'} "
            f"({time.perf_counter() - started:.1f}s)"
        )

    report = aggregate(results, provider=provider, model=model)
    write_outputs(report, results, cases, out_dir, provider=provider, model=model)
    return report


def aggregate(results: list[CaseResult], *, provider: str, model: str) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    by_category: dict[str, dict[str, float]] = {}
    for category in CATEGORIES:
        subset = [r for r in results if r.category == category]
        if subset:
            by_category[category] = {
                "cases": len(subset),
                "success_rate": round(sum(1 for r in subset if r.passed) / len(subset), 4),
            }

    retrieval = [r.retrieval for r in results if r.retrieval is not None]
    citations = [r.citations for r in results if r.citations is not None]
    latencies = [r.latency_ms for r in results if r.latency_ms > 0]
    total_claims = sum(r.claims for r in results)
    unsupported = sum(r.unsupported_claims for r in results)
    unsupported_rate = round(unsupported / total_claims, 4) if total_claims else None

    def mean(values: list[float]) -> float | None:
        return round(statistics.fmean(values), 4) if values else None

    def p95(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 1)

    return {
        "provider": provider,
        "model": model,
        "cases": total,
        "passed": passed,
        "success_rate": round(passed / total, 4) if total else None,
        "by_category": by_category,
        "retrieval_recall": mean([m.recall for m in retrieval if m.recall is not None]),
        "retrieval_precision": mean([m.precision for m in retrieval if m.precision is not None]),
        "citation_precision": mean([m.precision for m in citations if m.precision is not None]),
        "citation_recall": mean([m.recall for m in citations if m.recall is not None]),
        "unsupported_claims": unsupported,
        "unsupported_claim_rate": unsupported_rate,
        "tool_selection_accuracy": _tool_selection(results),
        "avg_latency_ms": mean(latencies),
        "p95_latency_ms": p95(latencies),
        "total_tokens": sum(r.tokens for r in results),
        "estimated_cost_usd": round(sum(r.estimated_cost_usd for r in results), 6),
    }


def _tool_selection(results: list[CaseResult]) -> float | None:
    """Fraction of cases where every expected tool was actually used."""
    relevant = [r for r in results if "tools" in r.checks]
    if not relevant:
        return None
    ok = sum(1 for r in relevant if r.checks["tools"])
    return round(ok / len(relevant), 4)


def write_outputs(
    report: dict[str, Any],
    results: list[CaseResult],
    cases: list[EvalCase],
    out_dir: Path,
    *,
    provider: str,
    model: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": provider,
        "model": model,
        "dataset_seed": 42,
        "git_rev": _git_rev(),
        "report": report,
        "results": [r.model_dump() for r in results],
    }
    (out_dir / f"results-{stamp}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(payload, cases), encoding="utf-8")
    print(f"results written to {out_dir}/report.md")


def render_markdown(payload: dict[str, Any], cases: list[EvalCase]) -> str:
    report = payload["report"]
    lines = [
        "# NexusGraph eval report",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Provider/model: `{payload['provider']}` / `{payload['model']}`",
        f"- Dataset seed: {payload['dataset_seed']} (synthetic corpus)",
        f"- Git revision: {payload['git_rev'] or 'unknown'}",
        "- Grading: deterministic only (see docs/EVALS.md)",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Success rate | {report['success_rate']} ({report['passed']}/{report['cases']}) |",
    ]
    for key, label in [
        ("retrieval_recall", "Retrieval recall (expected docs)"),
        ("retrieval_precision", "Retrieval precision"),
        ("citation_precision", "Citation precision"),
        ("citation_recall", "Citation recall (claims citing evidence)"),
        ("unsupported_claim_rate", "Unsupported-claim rate"),
        ("tool_selection_accuracy", "Tool-selection accuracy"),
        ("avg_latency_ms", "Average latency (ms)"),
        ("p95_latency_ms", "p95 latency (ms)"),
        ("total_tokens", "Total tokens"),
        ("estimated_cost_usd", "Estimated cost (USD)"),
    ]:
        value = report.get(key)
        lines.append(f"| {label} | {value if value is not None else 'n/a'} |")

    lines += [
        "",
        "## Per category",
        "",
        "| Category | Cases | Success rate |",
        "| --- | --- | --- |",
    ]
    for category, stats in report["by_category"].items():
        lines.append(f"| {category} | {stats['cases']} | {stats['success_rate']} |")

    lines += [
        "",
        "## Per case",
        "",
        "| ID | Category | Result | Failed checks |",
        "| --- | --- | --- | --- |",
    ]
    by_id = {r["case_id"]: r for r in payload["results"]}
    for case in cases:
        r = by_id[case.id]
        failed = ", ".join(r["failed"]) if r["failed"] else ""
        result = "PASS" if r["passed"] else "FAIL"
        if r.get("error"):
            result = f"ERROR ({r['error']})"
        lines.append(f"| {case.id} | {case.category} | {result} | {failed} |")

    lines += [
        "",
        "## Methodology",
        "",
        "- Answers were produced by the full agent pipeline (planner -> "
        "guarded tools -> evidence ledger -> synthesizer -> citation check).",
        "- Graders are deterministic: no LLM judged any answer.",
        "- Expected ids derive from the synthetic corpus manifest (seed 42); see evals/cases.py.",
        "- Token/cost figures are the run's own accounting; in `mock` "
        "provider mode there are no LLM calls on the answer path.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run", description="Run the NexusGraph deterministic eval suite"
    )
    parser.add_argument("--limit", type=int, default=None, help="run only the first N cases")
    parser.add_argument(
        "--cases", type=str, default=None, help="comma-separated case ids (e.g. R1,S1,M1)"
    )
    parser.add_argument("--out-dir", type=Path, default=_RESULTS_DIR)
    args = parser.parse_args(argv)

    cases = CASES
    if args.cases:
        wanted = {c.strip().upper() for c in args.cases.split(",")}
        cases = [c for c in CASES if c.id in wanted]
        missing = wanted - {c.id for c in cases}
        if missing:
            parser.error(f"unknown case ids: {sorted(missing)}")
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        parser.error("no cases selected")

    report = run_suite(cases, args.out_dir)
    print(f"\nsuccess rate: {report['success_rate']} ({report['passed']}/{report['cases']})")
    return 0 if report["passed"] == report["cases"] else 1


if __name__ == "__main__":
    sys.exit(main())
