"""HTTP API tests over a bootstrapped local-profile runtime."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from nexusgraph.api.app import create_app
from nexusgraph.config import Settings
from nexusgraph.runtime import bootstrap


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    tmp = tmp_path_factory.mktemp("api")
    return Settings(
        data_dir=tmp, database_url=f"sqlite:///{tmp}/nexusgraph.db", redis_url=None, _env_file=None
    )


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    bootstrap(settings, seed=42, regenerate=True)
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_health_and_ready(client: TestClient):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json()["status"] == "ready"


def test_index_served(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "NexusGraph" in resp.text


def test_query_endpoint_grounded(client: TestClient):
    resp = client.post(
        "/v1/query", json={"question": "How did patient enrolment change at Site A over time?"}
    )
    assert resp.status_code == 200
    answer = resp.json()
    assert answer["question_type"] in ("quantitative", "mixed")
    assert answer["evidence"]
    assert answer["claims"]
    for claim in answer["claims"]:
        for evidence_id in claim["evidence_ids"]:
            assert any(e["evidence_id"] == evidence_id for e in answer["evidence"])


def test_query_endpoint_rejects_blank(client: TestClient):
    resp = client.post("/v1/query", json={"question": "   "})
    assert resp.status_code == 422


def test_query_stream_emits_events_then_final(client: TestClient):
    with client.stream(
        "POST", "/v1/query/stream", json={"question": "Which trials have delayed milestones?"}
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        events: list[str] = []
        final: dict | None = None
        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                lines = block.splitlines()
                event = next((line[7:] for line in lines if line.startswith("event: ")), None)
                data = next((line[6:] for line in lines if line.startswith("data: ")), None)
                if event:
                    events.append(event)
                    if event == "final":
                        final = json.loads(data or "{}")
    assert "plan" in events
    assert "tool" in events
    assert events[-1] == "final"
    assert final is not None
    assert final["trace_id"]


def test_entity_lookup_roundtrip(client: TestClient):
    listing = client.get("/v1/entities", params={"q": "Site", "limit": 5})
    assert listing.status_code == 200
    entities = listing.json()
    assert entities
    entity_id = entities[0]["id"]
    detail = client.get(f"/v1/entities/{entity_id}")
    assert detail.status_code == 200
    assert detail.json()["entity"]["id"] == entity_id
    assert "relationships" in detail.json()


def test_entity_404(client: TestClient):
    assert client.get("/v1/entities/site:NOPE-1").status_code == 404


def test_document_roundtrip(client: TestClient):
    docs = client.get("/v1/documents").json()
    assert docs
    doc_id = docs[0]["id"]
    detail = client.get(f"/v1/documents/{doc_id}")
    assert detail.status_code == 200
    assert detail.json()["document"]["id"] == doc_id
    assert detail.json()["chunk_count"] >= 1


def test_trace_endpoint_after_query(client: TestClient):
    answer = client.post(
        "/v1/query",
        json={"question": "How many safety events are recorded at Site A?"},
    ).json()
    trace = client.get(f"/v1/traces/{answer['trace_id']}")
    assert trace.status_code == 200
    record = trace.json()
    assert record["question"].startswith("How many safety events")
    span_names = {s["name"] for s in record["spans"]}
    assert "plan" in span_names
    assert any(name.startswith("tool:") for name in span_names)


def test_api_key_required_when_configured(tmp_path_factory: pytest.TempPathFactory):
    tmp = tmp_path_factory.mktemp("api_key")
    settings = Settings(
        data_dir=tmp,
        database_url=f"sqlite:///{tmp}/nexusgraph.db",
        redis_url=None,
        api_key="sekrit",
        _env_file=None,
    )
    bootstrap(settings, seed=42, regenerate=True)
    from fastapi.testclient import TestClient as TC

    with TC(create_app(settings)) as client:
        assert client.post("/v1/query", json={"question": "anything"}).status_code == 401
        assert client.get("/v1/entities").status_code == 401
        assert client.get("/health").status_code == 200
        ok = client.post(
            "/v1/query", json={"question": "anything"}, headers={"X-API-Key": "sekrit"}
        )
        assert ok.status_code == 200
