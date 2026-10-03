"""LLM client protocol + request/response models + usage accounting."""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from nexusgraph.config import LLMSettings
from nexusgraph.domain.models import Usage

ROUGH_CHARS_PER_TOKEN = 4


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class CompletionRequest(BaseModel):
    messages: list[ChatMessage]
    task: str = "general"  # accounting label: plan | synthesize | extract_entities | ...
    max_tokens: int = 1024
    temperature: float = 0.0
    json_mode: bool = False


class CompletionResponse(BaseModel):
    text: str
    usage: Usage
    model: str
    provider: str
    finish_reason: str = "stop"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // ROUGH_CHARS_PER_TOKEN)


def estimate_cost(settings: LLMSettings, prompt_tokens: int, completion_tokens: int) -> float:
    cost = (
        prompt_tokens * settings.input_price_per_mtok
        + completion_tokens * settings.output_price_per_mtok
    ) / 1_000_000
    return round(cost, 6)


class LLMClient(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object from an LLM response (tolerates fences/prose)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in LLM response")
    return json.loads(cleaned[start : end + 1])


class UsageTracker(BaseModel):
    """Accumulates usage across LLM calls for one agent run."""

    total: Usage = Field(default_factory=Usage)

    def record(self, response: CompletionResponse) -> Usage:
        self.total.add(response.usage)
        return response.usage


def make_llm_client(settings: LLMSettings) -> LLMClient:
    """Factory: ``mock`` -> MockLLMClient; ``openai-compatible`` -> HTTP client."""
    if settings.provider == "openai-compatible":
        from nexusgraph.llm.openai_compat import OpenAICompatClient

        return OpenAICompatClient(settings)
    from nexusgraph.llm.mock import MockLLMClient

    return MockLLMClient()
