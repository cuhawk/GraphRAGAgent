"""Database engine + schema bootstrap (SQLAlchemy 2.0)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text

from nexusgraph.config import Settings
from nexusgraph.db.orm import Base
from nexusgraph.observability.logging import get_logger

logger = get_logger("db")


def create_engine_for(settings: Settings) -> Engine:
    url = settings.resolved_database_url
    if url.startswith("sqlite"):
        return create_engine(url, future=True)
    return create_engine(url, future=True, pool_pre_ping=True, pool_size=5, max_overflow=5)


def init_schema(engine: Engine, settings: Settings) -> None:
    """Idempotent schema creation.

    On PostgreSQL the pgvector extension is created first (requires a
    superuser/owner role - granted in docker-compose). The ORM metadata is the
    single source of truth; structured quantitative tables are created from the
    declarative schema in ``store.structured``.
    """
    url = str(engine.url)
    if url.startswith("postgresql"):
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:  # pragma: no cover - depends on DB privileges
            logger.warning("Could not create pgvector extension: %s", exc)
    Base.metadata.create_all(engine)
    from nexusgraph.store.structured import create_structured_tables

    create_structured_tables(engine)
    engine_kind = "postgres" if url.startswith("postgresql") else "sqlite"
    logger.info("schema ready (%s)", engine_kind)
