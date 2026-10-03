import pytest

from nexusgraph.domain.models import Aggregation, FilterCondition, OrderBy, QuerySpec
from nexusgraph.security.sqlguard import SqlGuardError, validate_query_spec
from nexusgraph.store.structured import STRUCTURED_SCHEMA, compile_query_spec


def test_valid_spec_passes_and_compiles() -> None:
    spec = QuerySpec(
        table="site_metrics_monthly",
        filters=[FilterCondition(column="site_id", op="eq", value="S-1001")],
        aggregations=[Aggregation(func="sum", column="patients_enrolled")],
        group_by=["month"],
        order_by=[OrderBy(column="month", direction="asc")],
    )
    validate_query_spec(spec, STRUCTURED_SCHEMA)
    compiled = str(compile_query_spec(spec))
    lowered = compiled.lower()
    assert lowered.startswith("select")
    assert "site_metrics_monthly" in lowered
    assert "sum" in lowered
    # no literal values are interpolated into the SQL text
    assert "S-1001" not in compiled


@pytest.mark.parametrize(
    "spec_builder",
    [
        lambda: QuerySpec(table="sqlite_master"),
        lambda: QuerySpec(table="site_metrics_monthly; DROP TABLE users"),
        lambda: QuerySpec(table="site_metrics_monthly", select=["site_id", "password_hash"]),
        lambda: QuerySpec(
            table="site_metrics_monthly", filters=[FilterCondition(column="evil", op="eq", value=1)]
        ),
        lambda: QuerySpec(
            table="site_metrics_monthly",
            filters=[FilterCondition(column="site_id", op="eq", value="x" * 300)],
        ),
        lambda: QuerySpec(
            table="site_metrics_monthly",
            filters=[FilterCondition(column="site_id", op="eq", value={"$gt": 1})],
        ),
        lambda: QuerySpec(
            table="site_metrics_monthly", aggregations=[Aggregation(func="sum", column=None)]
        ),
    ],
)
def test_invalid_specs_rejected(spec_builder) -> None:
    with pytest.raises(SqlGuardError):
        validate_query_spec(spec_builder(), STRUCTURED_SCHEMA)


def test_select_unknown_column_rejected() -> None:
    spec = QuerySpec(table="trials", select=["not_a_column"])
    with pytest.raises(SqlGuardError, match="does not exist"):
        validate_query_spec(spec, STRUCTURED_SCHEMA)
