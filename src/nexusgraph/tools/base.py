"""Tool execution infrastructure: errors, budgets, per-run context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nexusgraph.config import LimitsSettings
from nexusgraph.observability.tracing import TraceRecorder

if TYPE_CHECKING:
    from nexusgraph.runtime import Runtime


class ToolError(RuntimeError):
    """Any tool failure (guard violation, timeout, validation, empty budget)."""


class ToolBudgetExceeded(ToolError):
    pass


class ToolBudget:
    """Per-run cap on total tool calls (THREAT_MODEL: excessive tool use)."""

    def __init__(self, max_calls: int) -> None:
        self._max = max_calls
        self.used = 0
        self.calls_by_tool: dict[str, int] = {}

    def acquire(self, tool: str) -> None:
        if self.used >= self._max:
            raise ToolBudgetExceeded(
                f"tool-call budget exhausted ({self.used}/{self._max})")
        self.used += 1
        self.calls_by_tool[tool] = self.calls_by_tool.get(tool, 0) + 1


@dataclass
class ToolContext:
    """Everything a tool implementation may touch - nothing else."""

    runtime: Runtime
    limits: LimitsSettings
    budget: ToolBudget
    trace: TraceRecorder | None = None
    known_evidence_ids: set[str] | None = None
