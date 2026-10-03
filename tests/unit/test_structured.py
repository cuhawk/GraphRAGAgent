import pytest

from nexusgraph.domain.models import Aggregation, FilterCondition, OrderBy, QuerySpec
from nexusgraph.store.structured import run_structured_query


def test_aggregate_enrolment_by_month(seeded_engine, limits) -> None:
    spec = QuerySpec(
        table="site_metrics_monthly",
        filters=[FilterCondition(column="site_id", op="eq", value="S-1001"),
                 FilterCondition(column="trial_id", op="eq", value="T-2001")],
        aggregations=[Aggregation(func="sum", column="patients_enrolled")],
        group_by=["month"],
        order_by=[OrderBy(column="month", direction="asc")],
        limit=12,
    )
    result = run_structured_query(seeded_engine, spec, limits)
    assert result.row_count == 12
    assert result.columns == ["month", "sum_patients_enrolled"]
    enrolments = [int(row["sum_patients_enrolled"]) for row in result.rows]
    assert enrolments[0] > enrolments[-1]  # Site A declines


def test_plain_select_with_limit(seeded_engine, limits) -> None:
    spec = QuerySpec(
        table="safety_events",
        filters=[FilterCondition(column="severity", op="eq", value="HIGH")],
        order_by=[OrderBy(column="reported_at", direction="desc")],
        limit=50,
    )
    result = run_structured_query(seeded_engine, spec, limits)
    assert result.row_count >= 4
    assert all(row["severity"] == "HIGH" for row in result.rows)


def test_guard_blocks_unknown_table(seeded_engine, limits) -> None:
    spec = QuerySpec(table="users")
    with pytest.raises(Exception, match="allowlist"):
        run_structured_query(seeded_engine, spec, limits)


def test_like_filter(seeded_engine, limits) -> None:
    spec = QuerySpec(
        table="milestones",
        filters=[FilterCondition(column="name", op="like", value="%Database%")],
        limit=100,
    )
    result = run_structured_query(seeded_engine, spec, limits)
    assert result.row_count >= 5
