"""OpenAI-compatible chat-completions client (httpx, no vendor SDK)."""

from __future__ import annotations

import httpx

from nexusgraph.config import LLMSettings
from nexusgraph.llm.base import (
    CompletionRequest,
    CompletionResponse,
    estimate_cost,
    estimate_tokens,
)
from nexusgraph.observability.logging import get_logger

logger = get_logger("llm.openai_compat")


class OpenAICompatClient:
    provider = "openai-compatible"

    def __init__(self, settings: LLMSettings, timeout_s: float = 60.0) -> None:
        if not settings.base_url:
            raise ValueError("openai-compatible provider requires llm.base_url")
        if not settings.api_key:
            raise ValueError("openai-compatible provider requires llm.api_key")
        self._settings = settings
        self._model = settings.model
        self._timeout = timeout_s

    @property
    def model(self) -> str:
        return self._model

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._settings.api_key}",
        }
        prompt_text = "\n".join(m.content for m in request.messages)

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self._settings.base_url}/chat/completions", json=payload, headers=headers
            )
        if response.status_code >= 400:
            logger.warning("LLM HTTP %s: %s", response.status_code, response.text[:300])
            response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        text = choice["message"]["content"] or ""
        usage_data = data.get("usage") or {}
        prompt_tokens = int(usage_data.get("prompt_tokens") or estimate_tokens(prompt_text))
        completion_tokens = int(usage_data.get("completion_tokens") or estimate_tokens(text))
        return CompletionResponse(
            text=text,
            usage=_usage(prompt_tokens, completion_tokens, self._settings),
            model=data.get("model", self._model),
            provider=self.provider,
            finish_reason=choice.get("finish_reason", "stop"),
        )


def _usage(prompt_tokens: int, completion_tokens: int, settings: LLMSettings) -> object:
    from nexusgraph.domain.models import Usage

    return Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        llm_calls=1,
        estimated_cost_usd=estimate_cost(settings, prompt_tokens, completion_tokens),
    )
