from pathlib import Path

from nexusgraph.config import LimitsSettings, Settings


def test_local_profile_derives_sqlite_url(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path, database_url=None, _env_file=None)
    assert s.resolved_database_url.startswith("sqlite:///")
    assert "nexusgraph.db" in s.resolved_database_url


def test_postgres_profile_derives_postgres_url() -> None:
    s = Settings(profile="postgres", database_url=None, _env_file=None)
    assert s.resolved_database_url.startswith("postgresql+psycopg://")


def test_env_overrides_apply() -> None:
    s = Settings(
        profile="local",
        data_dir="x",
        llm={"provider": "openai-compatible", "model": "gpt-x"},
        _env_file=None,
    )
    assert s.llm.provider == "openai-compatible"
    assert s.llm.model == "gpt-x"


def test_limits_have_sane_defaults() -> None:
    limits = LimitsSettings()
    assert limits.max_rows >= 1
    assert limits.max_tool_calls_per_run >= 1
    assert limits.sparql_timeout_s > 0


def test_rdf_store_path_defaults_into_data_dir(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path, _env_file=None)
    assert s.resolved_rdf_store_path == tmp_path / "rdf"
