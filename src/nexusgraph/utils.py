"""Small shared utilities."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError


class ToolTimeoutError(RuntimeError):
    """A tool execution exceeded its wall-clock budget."""


def run_with_timeout(fn, timeout_s: float):  # noqa: ANN001 - generic callable
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
        raise ToolTimeoutError(
            f"execution exceeded {timeout_s:.1f}s wall-clock budget") from exc
    finally:
        pool.shutdown(wait=False)
