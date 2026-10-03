import pytest

from nexusgraph.observability.tracing import InMemoryTraceSink, Tracer


def test_span_nesting_and_durations() -> None:
    tracer = Tracer()  # no OTLP endpoint -> bridge disabled
    rec = tracer.start_trace()
    with rec.span("agent.run", question="q"):
        with rec.span("tool.run_sparql", tool="run_sparql"):
            pass
    rec.finish("ok")
    record = rec.record
    assert record.status == "ok"
    assert len(record.spans) == 2
    root, child = record.spans
    assert child.parent_span_id == root.span_id
    assert root.duration_ms is not None and root.duration_ms >= 0
    assert child.duration_ms is not None


def test_span_error_is_recorded_and_reraised() -> None:
    rec = Tracer().start_trace()
    with pytest.raises(ValueError, match="boom"):
        with rec.span("agent.run"):
            raise ValueError("boom")
    rec.finish("error")
    assert rec.record.spans[0].status == "error"
    assert "boom" in (rec.record.spans[0].error or "")


def test_in_memory_sink_bounded() -> None:
    sink = InMemoryTraceSink(max_traces=2)
    for _ in range(5):
        rec = Tracer().start_trace()
        rec.finish("ok")
        sink.save(rec.record)
    assert len(sink.list()) <= 2
