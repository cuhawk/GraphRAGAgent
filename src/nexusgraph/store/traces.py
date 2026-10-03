"""SQL-backed trace persistence (backs GET /v1/traces/{id})."""

from __future__ import annotations

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from nexusgraph.db.orm import TraceRow
from nexusgraph.observability.tracing import TraceRecord


class TraceSqlSink:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, record: TraceRecord) -> None:
        with Session(self._engine) as session:
            session.merge(
                TraceRow(
                    trace_id=record.trace_id,
                    question=record.question,
                    status=record.status,
                    error=record.error,
                    duration_ms=record.attributes.get("duration_ms"),
                    spans=[span.model_dump(mode="json") for span in record.spans],
                    attributes=record.attributes,
                    usage=record.attributes.get("usage", {}),
                )
            )
            session.commit()

    def get(self, trace_id: str) -> TraceRecord | None:
        with Session(self._engine) as session:
            row = session.get(TraceRow, trace_id)
            return self._from_row(row) if row else None

    def list(self, limit: int = 50) -> list[TraceRecord]:
        with Session(self._engine) as session:
            rows = (
                session.execute(select(TraceRow).order_by(TraceRow.created_at.desc()).limit(limit))
                .scalars()
                .all()
            )
        return [self._from_row(r) for r in rows]

    def purge(self, keep: int = 1_000) -> None:
        """Trim the table (bounded storage); keeps the most recent ``keep`` rows."""
        with Session(self._engine) as session:
            ids = [
                row[0]
                for row in session.execute(
                    select(TraceRow.trace_id).order_by(TraceRow.created_at.desc()).offset(keep)
                )
            ]
            if ids:
                session.execute(delete(TraceRow).where(TraceRow.trace_id.in_(ids)))
            session.commit()

    @staticmethod
    def _from_row(row: TraceRow) -> TraceRecord:
        return TraceRecord(
            trace_id=row.trace_id,
            created_at=row.created_at,
            question=row.question,
            status=row.status,
            error=row.error,
            spans=list(row.spans or []),
            attributes=row.attributes or {},
        )
