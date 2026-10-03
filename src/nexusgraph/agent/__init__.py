"""Agent package: planner, orchestrator, evidence ledger, synthesizers.

Public surface:

- :class:`AgentOrchestrator` — plan -> guarded tools -> evidence -> grounded
  answer (the entry point for the API, CLI, MCP and evals).
- :class:`EvidenceLedger` — the citation backbone.
- :class:`HeuristicRouter` / :class:`LLMPlanner` — planning.
- :class:`DeterministicSynthesizer` / :class:`LLMSynthesizer` — synthesis.
"""

from nexusgraph.agent.evidence import EvidenceLedger
from nexusgraph.agent.orchestrator import AgentOrchestrator
from nexusgraph.agent.planner import HeuristicRouter, LLMPlanner, make_planner
from nexusgraph.agent.synthesizer import (
    AnswerDraft,
    DeterministicSynthesizer,
    LLMSynthesizer,
    SynthesisRequest,
    ToolOutcome,
    make_synthesizer,
)

__all__ = [
    "AgentOrchestrator",
    "AnswerDraft",
    "DeterministicSynthesizer",
    "EvidenceLedger",
    "HeuristicRouter",
    "LLMPlanner",
    "LLMSynthesizer",
    "SynthesisRequest",
    "ToolOutcome",
    "make_planner",
    "make_synthesizer",
]
