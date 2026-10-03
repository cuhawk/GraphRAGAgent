# NexusGraph development tasks (Windows: use `uv run <cmd>` directly, or run
# these through GNU make / WSL).

.PHONY: bootstrap serve status mcp test test-fast lint format typecheck evals check ci

bootstrap:            ## generate + ingest the synthetic dataset (seed 42)
	uv run nexusgraph bootstrap

serve:                ## run the API + UI at http://127.0.0.1:8000
	uv run nexusgraph serve

status:               ## show store counts
	uv run nexusgraph status

mcp:                  ## run the read-only MCP server over stdio
	uv run nexusgraph mcp

test:                 ## full test suite
	uv run pytest

test-fast:            ## everything except integration-marked tests
	uv run pytest -m "not integration"

lint:                 ## ruff lint + format check
	uv run ruff check src tests evals
	uv run ruff format --check src evals

format:               ## auto-format
	uv run ruff format src evals tests
	uv run ruff check src tests evals --fix

typecheck:            ## mypy
	uv run mypy src evals

evals:                ## run the deterministic eval suite (writes evals/results/)
	uv run python -m evals.run

check: lint typecheck test evals  ## everything CI runs
