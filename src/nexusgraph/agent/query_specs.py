"""Typed QuerySpec builders used by the orchestrator.

Structured questions are answered by compiling these validated specs — the
model never writes raw SQL.
"""

from __future__ import annotations

from nexusgraph.domain.models import Aggregation, FilterCondition, OrderBy, QuerySpec


def site_monthly_metrics(site_id: str | None = None, trial_id: str | None = None) -> QuerySpec:
    filters = [
        FilterCondition(column=c, op="eq", value=v)
        for c, v in [("site_id", site_id), ("trial_id", trial_id)]
        if v
    ]
    return QuerySpec(
        table="site_metrics_monthly",
        filters=filters,
        aggregations=[
            Aggregation(func="sum", column="patients_enrolled"),
            Aggregation(func="sum", column="operational_cost"),
        ],
        group_by=["site_id", "month"],
        order_by=[OrderBy(column="site_id"), OrderBy(column="month")],
        limit=500,
    )


def delayed_milestones() -> QuerySpec:
    return QuerySpec(table="milestones", limit=100, order_by=[OrderBy(column="trial_id")])


def safety_events(site_id: str | None = None) -> QuerySpec:
    filters = [FilterCondition(column="site_id", op="eq", value=site_id)] if site_id else []
    return QuerySpec(
        table="safety_events",
        filters=filters,
        limit=100,
        order_by=[OrderBy(column="reported_at", direction="desc")],
    )


def region_enrolment_monthly(region_id: str | None = None) -> QuerySpec:
    filters = [FilterCondition(column="region_id", op="eq", value=region_id)] if region_id else []
    return QuerySpec(
        table="site_metrics_region_monthly",
        filters=filters,
        limit=100,
        order_by=[OrderBy(column="region_id"), OrderBy(column="month")],
    )


def region_capacity_monthly(region_id: str | None = None) -> QuerySpec:
    filters = [FilterCondition(column="region_id", op="eq", value=region_id)] if region_id else []
    return QuerySpec(
        table="investigator_capacity_region_monthly",
        filters=filters,
        limit=100,
        order_by=[OrderBy(column="region_id"), OrderBy(column="month")],
    )


def trial_rows(trial_id: str | None = None) -> QuerySpec:
    filters = [FilterCondition(column="trial_id", op="eq", value=trial_id)] if trial_id else []
    return QuerySpec(table="trials", filters=filters, limit=50)


def site_rows(site_id: str | None = None) -> QuerySpec:
    filters = [FilterCondition(column="site_id", op="eq", value=site_id)] if site_id else []
    return QuerySpec(table="sites", filters=filters, limit=50)


def counts_by(
    table: str,
    group_col: str,
    count_col: str | None = None,
    filters: list[FilterCondition] | None = None,
) -> QuerySpec:
    return QuerySpec(
        table=table,
        filters=filters or [],
        aggregations=[Aggregation(func="count", column=count_col)],
        group_by=[group_col],
        order_by=[OrderBy(column=group_col)],
        limit=100,
    )
