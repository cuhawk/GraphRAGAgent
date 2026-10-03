"""LLM adapter layer.

Two providers behind one protocol:

- ``OpenAICompatClient`` — any OpenAI-compatible endpoint (hosted models,
  vLLM, Ollama, LiteLLM, ...). No vendor SDK, no hard-wiring.
- ``MockLLMClient`` — deterministic, scripted test double; enables hermetic
  tests of LLM-dependent code paths. It is NOT used to fake intelligence: in
  ``mock`` provider mode the runtime skips LLM calls entirely and uses the
  deterministic planner/synthesizer instead.

Usage (prompt + completion tokens, estimated cost) is recorded for every call.
"""

from nexusgraph.llm.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    LLMClient,
    estimate_tokens,
    make_llm_client,
)
from nexusgraph.llm.mock import MockLLMClient
from nexusgraph.llm.openai_compat import OpenAICompatClient

__all__ = [
    "ChatMessage",
    "CompletionRequest",
    "CompletionResponse",
    "LLMClient",
    "MockLLMClient",
    "OpenAICompatClient",
    "estimate_tokens",
    "make_llm_client",
]
