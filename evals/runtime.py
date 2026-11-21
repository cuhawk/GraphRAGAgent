"""Build a fresh, offline evaluation database with the diagnostic packet."""

from pathlib import Path

from evals.diagnostic import add_records
from nexusgraph.config import LimitsSettings, LLMSettings, Settings
from nexusgraph.runtime import Runtime, ensure_bootstrapped, generate_dataset


def diagnostic_runtime(data_dir: Path) -> Runtime:
    settings = Settings.model_construct(
        profile="local",
        data_dir=data_dir,
        bootstrap_on_start=True,
        llm=LLMSettings(),
        limits=LimitsSettings(),
    )
    generate_dataset(settings)
    add_records(data_dir / "dataset")
    runtime, _ = ensure_bootstrapped(settings)
    return runtime
