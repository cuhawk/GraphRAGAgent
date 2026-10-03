"""FastAPI application: the HTTP surface over the agent and stores.

Endpoints (see README for examples):

- ``POST /v1/query``          grounded answer (JSON :class:`AgentAnswer`)
- ``POST /v1/query/stream``   the same run streamed as Server-Sent Events
                              (``plan`` / ``tool`` / ``synthesis`` / ``final``)
- ``GET  /v1/entities``       list/search entities (``?q=`` / ``?type=``)
- ``GET  /v1/entities/{id}``  one entity with relationships
- ``GET  /v1/documents``      list documents
- ``GET  /v1/documents/{id}`` one document (bounded text)
- ``GET  /v1/traces/{id}``    the recorded plan/tool/step trace of a run
- ``GET  /v1/traces``         recent traces
- ``GET  /health`` / ``/ready``
- ``GET  /``                  the minimal UI (static/index.html)

When ``settings.api_key`` is set, all ``/v1`` routes require the
``X-API-Key`` header; ``/health`` and ``/ready`` stay open for probes.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from nexusgraph.agent.orchestrator import AgentOrchestrator
from nexusgraph.config import Settings
from nexusgraph.domain.models import (
    AgentAnswer,
    DocumentDetail,
    Entity,
    EntityDetail,
)
from nexusgraph.observability.logging import configure_logging, get_logger
from nexusgraph.observability.tracing import TraceRecord
from nexusgraph.runtime import Runtime, ensure_bootstrapped

logger = get_logger("api")

_STATIC_DIR = pathlib.Path(__file__).parent / "static"


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8_000)


def _validate_question(question: str, settings: Settings) -> str:
    question = question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")
    if len(question) > settings.limits.max_input_chars:
        raise HTTPException(
            status_code=422,
            detail=f"question exceeds the {settings.limits.max_input_chars}-character limit",
        )
    return question


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory (used by ``nexusgraph serve``, tests and deployments)."""
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_json)
    runtime: Runtime
    runtime, _bootstrapped_now = ensure_bootstrapped(settings)
    orchestrator = AgentOrchestrator(runtime)

    app = FastAPI(
        title="NexusGraph",
        version="0.1.0",
        description=(
            "GraphRAG + Knowledge Graph Agent: grounded answers over "
            "RDF/SPARQL, structured SQL and hybrid document retrieval "
            "with citations and traces."
        ),
    )

    def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key and x_api_key != settings.api_key:
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    v1_auth = [Depends(require_api_key)]

    # ------------------------------------------------------------------ meta
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        if not runtime.is_bootstrapped():
            raise HTTPException(status_code=503, detail="stores are empty")
        return {"status": "ready"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    # ----------------------------------------------------------------- query
    @app.post("/v1/query", response_model=AgentAnswer, dependencies=v1_auth)
    def query(req: QueryRequest) -> AgentAnswer:
        question = _validate_question(req.question, settings)
        return orchestrator.run(question)

    @app.post("/v1/query/stream", dependencies=v1_auth)
    async def query_stream(req: QueryRequest) -> StreamingResponse:
        question = _validate_question(req.question, settings)
        queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()

        async def generator() -> AsyncIterator[str]:
            loop = asyncio.get_running_loop()

            def progress(event: str, payload: dict[str, Any]) -> None:
                data = json.dumps(payload, default=str)
                loop.call_soon_threadsafe(queue.put_nowait, (event, data))

            def work() -> AgentAnswer:
                try:
                    return orchestrator.run(question, progress_cb=progress)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            task = loop.run_in_executor(None, work)
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                yield f"event: {event}\ndata: {data}\n\n"
            try:
                answer = await task
            except Exception as exc:
                yield (f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n")
                return
            yield f"event: final\ndata: {answer.model_dump_json()}\n\n"

        return StreamingResponse(generator(), media_type="text/event-stream")

    # --------------------------------------------------------------- lookups
    @app.get("/v1/entities", response_model=list[Entity], dependencies=v1_auth)
    def list_entities(
        q: str | None = Query(default=None, max_length=200),
        type: str | None = Query(default=None, max_length=64),  # noqa: A002
        limit: int = Query(default=25, ge=1, le=200),
    ) -> list[Entity]:
        return runtime.entities.find_entities(q=q, entity_type=type, limit=limit)

    @app.get("/v1/entities/{entity_id}", response_model=EntityDetail, dependencies=v1_auth)
    def get_entity(entity_id: str) -> EntityDetail:
        detail = runtime.entities.get_entity_detail(entity_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return detail

    @app.get("/v1/documents", response_model=list[Any], dependencies=v1_auth)
    def list_documents(
        limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)
    ) -> list[Any]:
        return list(runtime.documents.list_documents(limit=limit, offset=offset))

    @app.get("/v1/documents/{document_id}", response_model=DocumentDetail, dependencies=v1_auth)
    def get_document(document_id: str) -> DocumentDetail:
        document = runtime.documents.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        chunks = runtime.documents.chunks_for_document(document_id)
        return DocumentDetail(document=document, chunk_count=len(chunks))

    # ---------------------------------------------------------------- traces
    @app.get("/v1/traces", response_model=list[TraceRecord], dependencies=v1_auth)
    def list_traces(
        limit: int = Query(default=25, ge=1, le=100),
    ) -> list[TraceRecord]:
        return runtime.trace_sink.list(limit=limit)

    @app.get("/v1/traces/{trace_id}", response_model=TraceRecord, dependencies=v1_auth)
    def get_trace(trace_id: str) -> TraceRecord:
        record = runtime.trace_sink.get(trace_id)
        if record is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return record

    return app
