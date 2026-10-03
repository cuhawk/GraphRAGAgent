# Contributing

Thanks for your interest in NexusGraph! This is a portfolio project, but it is
maintained with production-grade hygiene and contributions are welcome.

## Development setup

```bash
# Python 3.12+ and uv
uv sync --extra dev
uv run nexusgraph bootstrap     # generate + ingest the synthetic corpus
uv run pytest                   # full test suite
```

## Ground rules

1. **No invented numbers.** Any benchmark/eval figure in docs or comments must
   come from a run recorded in `evals/results/`. If you didn't measure it,
   write "not yet measured".
2. **Synthetic data only.** The bundled corpus is generated (seed 42). Do not
   commit real-world, patient or company data, and do not make medical claims
   in synthetic content.
3. **Guards are the boundary.** New tool paths must pass the SPARQL/SQL guards
   and run under the shared `ToolBudget` with bounded outputs. Raw SQL from
   model output is never accepted — extend `QuerySpec`/builders instead.
4. **Citations are ledger-only.** Any new tool must emit results convertible
   into `Evidence` (source id, source type, location). Claims may only cite
   ledger ids; the orchestrator's re-check is not optional.
5. **Type it, lint it.** `mypy src evals` and `ruff check src tests evals`
   must be clean (CI enforces both). Lazy imports are a deliberate pattern
   (see pyproject comment on PLC0415).

## Workflow

1. Fork/branch from `main`.
2. Add or change code with tests. New features need:
   - unit tests for the logic,
   - eval cases if they change answer behaviour (`evals/cases.py`),
   - a re-run of `python -m evals.run` with results attached if the change
     moves metrics.
3. Run the full local gate:

   ```bash
   uv run ruff check src tests evals
   uv run mypy src evals
   uv run pytest
   uv run python -m evals.run
   ```

4. Update docs (`README.md`, `docs/*.md`) when behaviour, config or endpoints
   change.
5. Open a PR with a short description and the eval delta (if any).

## Test layout

- `tests/unit/` — hermetic, SQLite/in-memory, fast.
- `tests/integration/` — boots the full runtime (still local-profile; no
  external services needed to develop).
- CI additionally runs against PostgreSQL + pgvector and Redis services.

## Code style

Ruff (line length 100) + `ruff format`. Docstrings on public modules/classes;
comments explain constraints, not narration. Keep module docstrings honest —
they are the first thing a reader sees.
