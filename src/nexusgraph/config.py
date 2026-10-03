"""Application configuration.

Two runtime profiles exist:

- ``local``    — SQLite + in-process vector store + in-memory RDF + optional Redis.
                 Zero external services; used for development, tests and hermetic evals.
- ``postgres`` — PostgreSQL (+pgvector) + file-backed RDF store + Redis.
                 The production-ish profile wired up by ``docker-compose.yml``.

Every setting can be overridden with environment variables using the
``NEXUSGRAPH_`` prefix and ``__`` as the nesting delimiter, e.g.
``NEXUSGRAPH_LLM__PROVIDER=openai-compatible``. A ``.env`` file in the repo
root is honoured as well (see ``.env.example``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Profile = Literal["local", "postgres"]


class LLMSettings(BaseModel):
    """LLM + embedding backend configuration (vendor-neutral)."""

    provider: Literal["mock", "openai-compatible"] = "mock"
    base_url: str | None = None
    api_key: str | None = None
    model: str = "mock-deterministic"
    temperature: float = 0.0
    max_tokens: int = 1024

    embedding_provider: Literal["hash", "openai-compatible"] = "hash"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 256

    # Rough cost accounting only (USD per 1M tokens). Values are estimates the
    # operator sets for their chosen model; never presented as real billing.
    input_price_per_mtok: float = 0.0
    output_price_per_mtok: float = 0.0


class LimitsSettings(BaseModel):
    """Hard resource limits enforced by tools and guards (see docs/THREAT_MODEL.md)."""

    max_tool_calls_per_run: int = Field(default=12, ge=1)
    max_rows: int = Field(default=500, ge=1)
    max_result_bytes: int = Field(default=64_000, ge=1)
    max_input_chars: int = Field(default=8_000, ge=1)
    max_chunk_chars: int = Field(default=800, ge=100)
    max_retrieval_chars: int = Field(default=12_000, ge=1)
    tool_timeout_s: float = Field(default=20.0, gt=0)
    sparql_timeout_s: float = Field(default=5.0, gt=0)
    sql_timeout_s: float = Field(default=5.0, gt=0)
    retrieval_k: int = Field(default=6, ge=1)


class AgentSettings(BaseModel):
    max_hops: int = Field(default=3, ge=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUSGRAPH_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    profile: Profile = "local"
    data_dir: Path = Path("./data")

    # None => derived from profile in resolved_database_url / resolved_rdf_store_path.
    database_url: str | None = None
    redis_url: str | None = None
    rdf_store_path: Path | None = None

    # Seed + ingest the synthetic dataset automatically when the DB is empty
    # (used by the API entrypoint / docker compose bootstrap step).
    bootstrap_on_start: bool = True

    # Optional single-tenant API key; when unset the API is open (documented limitation).
    api_key: str | None = None

    log_level: str = "INFO"
    log_json: bool = False

    # OpenTelemetry OTLP endpoint; unset = spans stay in the app-local trace store.
    otlp_endpoint: str | None = None

    llm: LLMSettings = Field(default_factory=LLMSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.profile == "postgres":
            return "postgresql+psycopg://nexusgraph:nexusgraph@localhost:5432/nexusgraph"
        return f"sqlite:///{(self.data_dir / 'nexusgraph.db').as_posix()}"

    @property
    def resolved_rdf_store_path(self) -> Path:
        if self.rdf_store_path is not None:
            return self.rdf_store_path
        if self.profile == "postgres":
            return self.data_dir / "rdf"
        return self.data_dir / "rdf"  # local profile still persists; tests pass ":memory:"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings; entrypoints only. Libraries receive Settings explicitly."""
    return Settings()
