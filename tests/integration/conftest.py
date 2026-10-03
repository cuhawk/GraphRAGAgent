"""Integration-test fixtures: a fully bootstrapped local-profile runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexusgraph.agent.orchestrator import AgentOrchestrator
from nexusgraph.config import Settings
from nexusgraph.runtime import bootstrap, build_runtime


@pytest.fixture(scope="module")
def bootstrapped_runtime(tmp_path_factory: pytest.TempPathFactory):
    tmp: Path = tmp_path_factory.mktemp("agent_e2e")
    settings = Settings(
        data_dir=tmp,
        database_url=f"sqlite:///{tmp}/nexusgraph.db",
        redis_url=None,
        _env_file=None,
    )
    bootstrap(settings, seed=42, regenerate=True)
    runtime = build_runtime(settings)
    yield runtime
    runtime.engine.dispose()


@pytest.fixture(scope="module")
def orchestrator(bootstrapped_runtime) -> AgentOrchestrator:
    return AgentOrchestrator(bootstrapped_runtime)
