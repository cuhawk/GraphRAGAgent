"""SQL guard: validating QuerySpecs before compilation.

The model assembles a typed :class:`QuerySpec` (Pydantic-validated); this
module is the second line of defence, checking the spec against the schema
allowlist. Execution is parameterised (no string interpolation), row-capped
and read-only. Raw SQL from any model output is never accepted.
"""

from __future__ import annotations

import re

from nexusgraph.domain.models import QuerySpec

_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_MAX_VALUE_CHARS = 256


class SqlGuardError(ValueError):
    """Raised when a QuerySpec fails validation."""


def validate_identifier(name: str, kind: str = "identifier") -> str:
    if not _IDENTIFIER_RE.match(name):
        raise SqlGuardError(f"invalid {kind}: {name!r}")
    return name


def validate_table(table: str, schema: dict[str, dict[str, str]]) -> str:
    validate_identifier(table, "table name")
    if table not in schema:
        raise SqlGuardError(f"table {table!r} is not in the allowlist")
    return table


def validate_columns(table: str, columns: list[str],
                     schema: dict[str, dict[str, str]]) -> list[str]:
    allowed = schema[table]
    for column in columns:
        validate_identifier(column, "column name")
        if column not in allowed:
            raise SqlGuardError(f"column {column!r} does not exist in table {table!r}")
    return columns


def validate_filter_values(spec: QuerySpec) -> None:
    for cond in spec.filters:
        validate_identifier(cond.column, "filter column")
        if isinstance(cond.value, str):
            if len(cond.value) > _MAX_VALUE_CHARS:
                raise SqlGuardError("filter value too long")
            if any(ch in cond.value for ch in ("\x00", "\r", "\n")):
                raise SqlGuardError("filter value contains control characters")
        elif isinstance(cond.value, (list, tuple)):
            if len(cond.value) > 100:
                raise SqlGuardError("too many values in IN filter")
        elif not isinstance(cond.value, (int, float, bool)) and cond.value is not None:
            raise SqlGuardError(f"unsupported filter value type: {type(cond.value).__name__}")


def validate_query_spec(spec: QuerySpec, schema: dict[str, dict[str, str]]) -> QuerySpec:
    """Full validation pass; raises SqlGuardError on any violation."""
    validate_table(spec.table, schema)
    select = spec.select or list(schema[spec.table].keys())
    validate_columns(spec.table, select, schema)
    validate_columns(spec.table, [f.column for f in spec.filters], schema)
    for agg in spec.aggregations:
        if agg.column is not None:
            validate_columns(spec.table, [agg.column], schema)
        elif agg.func != "count":
            raise SqlGuardError("aggregation without a column is only valid for count")
    if spec.group_by:
        validate_columns(spec.table, spec.group_by, schema)
        if not spec.aggregations:
            raise SqlGuardError("group_by requires at least one aggregation")
    for ob in spec.order_by:
        validate_columns(spec.table, [ob.column], schema)
    validate_filter_values(spec)
    return spec
