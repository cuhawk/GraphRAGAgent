"""Structured (relational) data access.

The quantitative domain tables are defined *declaratively* here: the schema
dict is the single source of truth for table creation, CSV ingestion and the
SQL tool's table/column allowlist. The agent never writes raw SQL — it fills a
typed :class:`QuerySpec` which is validated against this schema, compiled to a
parameterised SELECT, and executed under row/byte caps and a timeout.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql import Select

from nexusgraph.config import LimitsSettings
from nexusgraph.domain.models import QuerySpec, StructuredQueryResult
from nexusgraph.observability.logging import get_logger
from nexusgraph.security.sqlguard import validate_query_spec
from nexusgraph.utils import ToolTimeoutError, run_with_timeout

logger = get_logger("store.structured")

_STR = String(128)
_TXT = String(512)

# table -> {column: sql type}. Types: "str" | "text" | "int" | "float".
STRUCTURED_SCHEMA: dict[str, dict[str, str]] = {
    "trials": {
        "trial_id": "str",
        "codename": "text",
        "phase": "str",
        "company_id": "str",
        "status": "str",
        "start_date": "str",
        "planned_end_date": "str",
    },
    "sites": {
        "site_id": "str",
        "name": "text",
        "country_id": "str",
        "hospital_id": "str",
        "metric_pattern": "str",
    },
    "site_metrics_monthly": {
        "site_id": "str",
        "trial_id": "str",
        "month": "str",
        "patients_enrolled": "int",
        "operational_cost": "int",
    },
    "milestones": {
        "milestone_id": "str",
        "trial_id": "str",
        "name": "text",
        "due_date": "str",
        "completed_date": "str",
    },
    "investigators": {
        "investigator_id": "str",
        "name": "text",
        "site_id": "str",
        "seniority": "str",
    },
    "investigator_capacity_monthly": {
        "investigator_id": "str",
        "month": "str",
        "capacity_index": "float",
    },
    "safety_events": {
        "event_id": "str",
        "site_id": "str",
        "trial_id": "str",
        "compound_id": "str",
        "severity": "str",
        "reported_at": "str",
        "description": "text",
    },
    "products": {
        "product_id": "str",
        "name": "text",
        "company_id": "str",
        "compound_id": "str",
    },
    "compounds": {"compound_id": "str", "name": "text", "target": "text"},
    "companies": {"company_id": "str", "name": "text", "hq_country_id": "str"},
    "countries": {"country_id": "str", "name": "text", "region_id": "str"},
    "regions": {"region_id": "str", "name": "text"},
    "trials_compounds": {"trial_id": "str", "compound_id": "str"},
    "site_metrics_region_monthly": {
        "region_id": "str",
        "month": "str",
        "total_patients_enrolled": "int",
        "total_operational_cost": "int",
    },
    "investigator_capacity_region_monthly": {
        "region_id": "str",
        "month": "str",
        "avg_capacity_index": "float",
    },
}

_COLUMN_TYPES: dict[str, Any] = {"str": _STR, "text": _TXT, "int": Integer, "float": Float}

_metadata: MetaData | None = None


def structured_metadata() -> MetaData:
    """SQLAlchemy metadata for the structured schema (cached)."""
    global _metadata  # noqa: PLW0603 - deliberate module-level cache
    if _metadata is None:
        md = MetaData()
        for table, columns in STRUCTURED_SCHEMA.items():
            Table(table, md, *[Column(col, _COLUMN_TYPES[typ]) for col, typ in columns.items()])
        _metadata = md
    return _metadata


def create_structured_tables(engine: Engine) -> None:
    structured_metadata().create_all(engine)


def _coerce(value: Any, sql_type: str) -> Any:
    if value is None or value == "":
        return None if sql_type in ("int", "float") else value
    if sql_type == "int":
        return int(value)
    if sql_type == "float":
        return float(value)
    return str(value)


def insert_rows(engine: Engine, table: str, rows: list[dict[str, Any]]) -> int:
    """Bulk insert CSV-derived rows (used by ingestion only)."""
    columns = STRUCTURED_SCHEMA[table]
    payload = [{col: _coerce(row.get(col), typ) for col, typ in columns.items()} for row in rows]
    md = structured_metadata()
    with engine.begin() as conn:
        conn.execute(md.tables[table].insert(), payload)
    return len(payload)


def compile_query_spec(spec: QuerySpec) -> Select:
    """Compile a (already validated) QuerySpec to a parameterised SELECT."""
    md = structured_metadata()
    table = md.tables[spec.table]

    if spec.aggregations:
        expr: list[Any] = [table.c[col] for col in spec.group_by]
        for agg in spec.aggregations:
            if agg.func == "count":
                label = "count" if agg.column is None else f"count_{agg.column}"
                col_expr = func.count() if agg.column is None else func.count(table.c[agg.column])
                expr.append(col_expr.label(label))
            else:
                # sqlguard rejects non-count aggregations without a column.
                if agg.column is None:
                    raise ValueError(f"aggregation {agg.func} requires a column")
                expr.append(
                    getattr(func, agg.func)(table.c[agg.column]).label(f"{agg.func}_{agg.column}")
                )
    else:
        columns = list(spec.select) if spec.select else list(STRUCTURED_SCHEMA[spec.table])
        expr = [table.c[col] for col in columns]

    query = select(*expr)
    for cond in spec.filters:
        column = table.c[cond.column]
        if cond.op == "eq":
            query = query.where(column == cond.value)
        elif cond.op == "neq":
            query = query.where(column != cond.value)
        elif cond.op == "gt":
            query = query.where(column > cond.value)
        elif cond.op == "gte":
            query = query.where(column >= cond.value)
        elif cond.op == "lt":
            query = query.where(column < cond.value)
        elif cond.op == "lte":
            query = query.where(column <= cond.value)
        elif cond.op == "in":
            query = query.where(column.in_(list(cond.value)))
        elif cond.op == "like":
            query = query.where(column.like(cond.value))
    for col in spec.group_by:
        query = query.group_by(table.c[col])
    for ob in spec.order_by:
        query = query.order_by(
            table.c[ob.column].desc() if ob.direction == "desc" else table.c[ob.column].asc()
        )
    return query.limit(spec.limit)


def run_structured_query(
    engine: Engine,
    spec: QuerySpec,
    limits: LimitsSettings,
) -> StructuredQueryResult:
    """Validate, compile, execute and cap a structured query."""
    validate_query_spec(spec, STRUCTURED_SCHEMA)
    query = compile_query_spec(spec)

    sql_text = str(query.compile(compile_kwargs={"literal_binds": False}))
    started = time.perf_counter()

    def _execute() -> list[dict[str, Any]]:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(
                    text(f"SET LOCAL statement_timeout = {int(limits.sql_timeout_s * 1000)}")
                )
            result = conn.execute(query)
            return [dict(row._mapping) for row in result.fetchmany(limits.max_rows + 1)]

    try:
        rows = run_with_timeout(_execute, limits.sql_timeout_s * 2 + 1)
    except ToolTimeoutError:
        logger.warning("structured query timed out")
        raise

    truncated = len(rows) > limits.max_rows
    rows = rows[: limits.max_rows]
    result = StructuredQueryResult(
        executed_sql=sql_text,
        columns=list(rows[0].keys()) if rows else [],
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )
    logger.info(
        "structured query ok",
        extra={
            "tool": "query_structured_data",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return result
