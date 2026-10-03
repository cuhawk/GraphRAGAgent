"""Per-run tracing: an app-local trace recorder (queryable via /v1/traces/{id})
optionally mirrored to OpenTelemetry when an OTLP endpoint is configured.

Design notes:

- The app-local recorder is authoritative: trace inspection must work with no
  collector running. Spans are persisted through a :class:`TraceSink`.
- When OTel is configured we *also* emit real OTel spans so standard backends
  (Jaeger, Grafana Tempo, ...) can consume them; the nexusgraph trace id is
  attached as a span attribute for correlation.
- Bridge failures never break the request path.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from nexusgraph.observability.logging import get_logger

logger = get_logger("tracing")

TRACE_ID_ATTR = "nexusgraph.trace_id"


class SpanRecord(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    name: str
    start_ns: int
    end_ns: int | None = None
    duration_ms: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"
    error: str | None = None


class TraceRecord(BaseModel):
    trace_id: str
    created_at: datetime
    question: str | None = None
    status: str = "running"  # running | ok | error
    error: str | None = None
    spans: list[SpanRecord] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceSink(Protocol):
    def save(self, record: TraceRecord) -> None: ...

    def get(self, trace_id: str) -> TraceRecord | None: ...

    def list(self, limit: int = 50) -> list[TraceRecord]: ...


class InMemoryTraceSink:
    """Bounded sink used by tests and as fallback when no DB is bound."""

    def __init__(self, max_traces: int = 200) -> None:
        self._max = max_traces
        self._traces: dict[str, TraceRecord] = {}

    def save(self, record: TraceRecord) -> None:
        self._traces[record.trace_id] = record
        if len(self._traces) > self._max:
            self._traces.pop(next(iter(self._traces)))

    def get(self, trace_id: str) -> TraceRecord | None:
        return self._traces.get(trace_id)

    def list(self, limit: int = 50) -> list[TraceRecord]:
        return list(self._traces.values())[-limit:]


class _OtelBridge:
    """Lazily-initialized OpenTelemetry exporter; a no-op when disabled/broken."""

    def __init__(self, otlp_endpoint: str | None) -> None:
        self._tracer: Any | None = None
        if not otlp_endpoint:
            return
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(resource=Resource({"service.name": "nexusgraph"}))
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer("nexusgraph")
        except Exception as exc:  # pragma: no cover - depends on optional env
            logger.warning("OpenTelemetry disabled: %s", exc)

    @contextmanager
    def span(self, name: str, trace_id: str, attributes: dict[str, Any]) -> Iterator[None]:
        if self._tracer is None:
            yield
            return
        try:
            with self._tracer.start_as_current_span(name) as otel_span:
                otel_span.set_attribute(TRACE_ID_ATTR, trace_id)
                for key, value in attributes.items():
                    otel_span.set_attribute(key, _otel_value(value))
                yield
        except Exception:  # pragma: no cover - never break the request path
            yield


def _otel_value(value: Any) -> Any:
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)[:200]


class TraceRecorder:
    """Collects spans for one agent run."""

    def __init__(self, trace_id: str | None = None, otel: _OtelBridge | None = None) -> None:
        self.record = TraceRecord(
            trace_id=trace_id or uuid.uuid4().hex,
            created_at=datetime.now(UTC),
        )
        self._otel = otel
        self._stack: list[SpanRecord] = []

    @property
    def trace_id(self) -> str:
        return self.record.trace_id

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[SpanRecord]:
        parent = self._stack[-1] if self._stack else None
        span = SpanRecord(
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=parent.span_id if parent else None,
            name=name,
            start_ns=time_ns(),
            attributes=_safe_attrs(attributes),
        )
        self.record.spans.append(span)
        self._stack.append(span)
        with _otel_span(self._otel, name, self.trace_id, span.attributes):
            try:
                yield span
            except Exception as exc:
                span.status = "error"
                span.error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                span.end_ns = time_ns()
                span.duration_ms = round((span.end_ns - span.start_ns) / 1e6, 3)
                self._stack.pop()

    def set_question(self, question: str) -> None:
        self.record.question = question

    def set_attributes(self, **attrs: Any) -> None:
        self.record.attributes.update(_safe_attrs(attrs))

    def finish(self, status: str = "ok", error: str | None = None) -> None:
        self.record.status = status
        self.record.error = error
        for span in self.record.spans:
            if span.end_ns is None:
                span.end_ns = time_ns()
                span.duration_ms = round((span.end_ns - span.start_ns) / 1e6, 3)


def time_ns() -> int:
    return time.time_ns()


def _safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v)[:400] if not isinstance(v, (int, float, bool)) else v)
            for k, v in attrs.items()}


@contextmanager
def _otel_span(otel: _OtelBridge | None, name: str, trace_id: str,
               attributes: dict[str, Any]) -> Iterator[None]:
    if otel is None:
        yield
        return
    with otel.span(name, trace_id, attributes):
        yield


class Tracer:
    """Creates recorders; one per process (or per request scope in the API layer)."""

    def __init__(self, otlp_endpoint: str | None = None) -> None:
        self._otel = _OtelBridge(otlp_endpoint)

    def start_trace(self, trace_id: str | None = None) -> TraceRecorder:
        return TraceRecorder(trace_id=trace_id, otel=self._otel)
