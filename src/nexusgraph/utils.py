"""Small shared utilities."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any


class ToolTimeoutError(RuntimeError):
    """A tool execution exceeded its wall-clock budget."""


class ToolValidationError(RuntimeError):
    """A query/result form is not supported by the guarded path."""


def run_with_timeout(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run ``fn`` in a worker thread and bound the wall-clock wait.

    If the worker overruns, the caller gets :class:`ToolTimeoutError` and the
    worker is abandoned (in-process engines cannot be killed mid-call; the
    real enforcement on PostgreSQL is ``statement_timeout``). See
    docs/THREAT_MODEL.md for the layered-controls discussion.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=timeout_s)
    except FuturesTimeoutError as exc:
        raise ToolTimeoutError(f"execution exceeded {timeout_s:.1f}s wall-clock budget") from exc
    finally:
        pool.shutdown(wait=False)
