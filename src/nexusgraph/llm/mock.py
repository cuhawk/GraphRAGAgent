"""Deterministic scripted LLM client for tests (a test double, not a brain).

``MockLLMClient`` returns canned or handler-produced responses keyed by the
request's ``task`` label. It lets the LLM-dependent code paths (planner,
synthesizer, optional extractor) be tested without network access and without
flaky expectations. Runtime ``mock`` mode does not call it at all — the
deterministic planner/synthesizer handle those runs directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nexusgraph.llm.base import CompletionRequest, CompletionResponse, estimate_tokens


class MockLLMClient:
    provider = "mock"

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        handlers: dict[str, Callable[[CompletionRequest], str]] | None = None,
        model: str = "mock-deterministic",
    ) -> None:
        self._responses = responses or {}
        self._handlers = handlers or {}
        self._model = model
        self.calls: list[CompletionRequest] = []

    @property
    def model(self) -> str:
        return self._model

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.calls.append(request)
        handler = self._handlers.get(request.task)
        if handler is not None:
            text = handler(request)
        else:
            text = self._responses.get(
                request.task,
                self._default_response(request),
            )
        return CompletionResponse(
            text=text,
            usage=_usage(request, text),
            model=self._model,
            provider=self.provider,
        )

    @staticmethod
    def _default_response(request: CompletionRequest) -> str:
        last = request.messages[-1].content if request.messages else ""
        if request.json_mode:
            payload: dict[str, Any] = {"task": request.task, "echo": last[:200]}
            return str(payload).replace("'", '"')
        return f"[mock:{request.task}] {last[:160]}"


def _usage(request: CompletionRequest, text: str) -> object:
    from nexusgraph.domain.models import Usage

    prompt_tokens = estimate_tokens("\n".join(m.content for m in request.messages))
    completion_tokens = estimate_tokens(text)
    return Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        llm_calls=1,
        estimated_cost_usd=0.0,
    )
