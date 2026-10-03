"""Lightweight deterministic analysis over structured evidence rows.

Used by the deterministic synthesizer to make honest quantitative claims
(slopes/trends) without an LLM. Shared by the evaluation graders.
"""

from __future__ import annotations


def linear_slope(points: list[tuple[float, float]]) -> float:
    """Least-squares slope of (x, y) points; 0.0 when undefined."""
    n = len(points)
    if n < 2:
        return 0.0
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denom = sum((x - mean_x) ** 2 for x, _ in points)
    if denom == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / denom


def series_from_rows(
    rows: list[dict],
    group_col: str,
    x_col: str,
    y_col: str,
) -> dict[str, list[tuple[float, float]]]:
    """Group rows into ordered numeric series: {group: [(x, y), ...]}."""
    series: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        group = str(row.get(group_col, ""))
        x_raw, y_raw = row.get(x_col), row.get(y_col)
        if x_raw is None or y_raw is None:
            continue
        try:
            x = float(x_raw)
            y = float(y_raw)
        except (TypeError, ValueError):
            continue
        series.setdefault(group, []).append((x, y))
    for points in series.values():
        points.sort()
    return series


def trend(series: list[tuple[float, float]], threshold: float = 0.0) -> str:
    """'increasing' | 'decreasing' | 'flat' based on the linear slope."""
    slope = linear_slope(series)
    if slope > threshold:
        return "increasing"
    if slope < -threshold:
        return "decreasing"
    return "flat"


def first_last(series: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not series:
        return None
    return series[0][1], series[-1][1]
