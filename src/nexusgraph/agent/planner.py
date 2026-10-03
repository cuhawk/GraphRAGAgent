"""Planner / Router: decides which tools a question needs.

Two implementations behind one protocol:

- :class:`HeuristicRouter` — deterministic keyword/intent rules. Used in
  ``mock`` provider mode (hermetic tests + evals) and as the fallback for the
  LLM planner.
- :class:`LLMPlanner` — asks the model to choose tools + arguments hints from
  the tool registry; every response is validated and falls back to the
  heuristic router on any deviation.

Steps carry *intents*, not raw queries: the orchestrator expands an intent
into guarded SPARQL / typed QuerySpec / retrieval arguments. The planner
therefore cannot produce an unguarded query by construction.
"""

from __future__ import annotations

import re
from typing import Any, cast

from nexusgraph.agent.sparql_templates import PREFIX_BLOCK
from nexusgraph.domain.models import (
    Entity,
    Plan,
    PlanStep,
    QuestionType,
    ToolName,
    Usage,
)
from nexusgraph.llm.base import LLMClient
from nexusgraph.observability.logging import get_logger

logger = get_logger("agent.planner")

QUANT_RE = re.compile(
    r"\b(enrolment|enrollment|cost|costs|capacity|trend|increase[sd]?|increasing|"
    r"decrease[sd]?|declin\w*|fall\w*|ris\w*|how many|count|total|average|avg|sum|"
    r"per month|monthly|number of)\b", re.IGNORECASE)
RELATION_RE = re.compile(
    r"\b(linked|link|connected|connect|associated|association|mention\w*|derived|"
    r"works? (at|for)|located|belongs?|related|relation\w*|between|compare\w*|"
    r"versus|vs\.?|higher|lower|risk|support\w*|evidence|which (products?|studies?|"
    r"trials?|documents?|sites?|compounds?))\b", re.IGNORECASE)
DOC_RE = re.compile(
    r"\b(document|documents|report|reports|dossier|written|write[- ]?up|"
    r"research|evidence)\b", re.IGNORECASE)
DELAYED_RE = re.compile(r"\bdelayed?\b|\blate\b|\boverdue\b", re.IGNORECASE)
SAFETY_RE = re.compile(r"\bsafety\b|\bincident\w*\b|\bseverity\b", re.IGNORECASE)
REGION_RE = re.compile(r"\bregions?\b|\bcluster\b", re.IGNORECASE)
UNANSWERABLE_RE = re.compile(
    r"\b(market share|revenue|profit\w*|stock price|share price|weather|salary|"
    r"ceo|headquarters address|french|spanish|birthday|founded)\b", re.IGNORECASE)
LOOKUP_RE = re.compile(
    r"\b(tell me about|describe|what is|who is|details? (of|for)|show)\b",
    re.IGNORECASE)
COMPARISON_RE = re.compile(r"\b(compare\w*|versus|vs\.?|higher .{0,20} than|"
                           r"lower .{0,20} than|difference between)\b", re.IGNORECASE)


def _step(tool: ToolName, rationale: str, **args: Any) -> PlanStep:
    return PlanStep(tool=tool, rationale=rationale, args=args)


class HeuristicRouter:
    """Deterministic question -> plan mapping (see docs/ARCHITECTURE.md)."""

    def plan(self, question: str, resolved: list[Entity]) -> Plan:
        q = question
        entity_ids = [e.id for e in resolved]
        region_id = next((e.id.split(":", 1)[1] for e in resolved
                          if e.id.startswith("region:")), None)

        if UNANSWERABLE_RE.search(q):
            return Plan(
                question_type="unanswerable",
                steps=[],
                rationale="Question asks for data this system does not model "
                          "(e.g. financials, demographics); refusing rather than guessing.")

        wants_docs = bool(DOC_RE.search(q))
        wants_quant = bool(QUANT_RE.search(q))
        wants_rel = bool(RELATION_RE.search(q))

        if wants_rel and wants_quant:
            steps: list[PlanStep] = []
            if SAFETY_RE.search(q) and "report" in q.lower():
                steps.append(_step(
                    "run_sparql",
                    "Find sites associated with compounds named in safety reports.",
                    intent="compounds_with_safety_sites"))
            elif DELAYED_RE.search(q):
                steps.append(_step(
                    "run_sparql",
                    "Find products connected to trials with delayed milestones.",
                    intent="products_of_delayed_trials"))
            elif entity_ids:
                steps.append(_step(
                    "run_sparql",
                    "Traverse graph neighbours of the entities in the question.",
                    intent="entity_neighbours", entity_id=entity_ids[0]))
            if REGION_RE.search(q):
                steps.append(_step(
                    "query_structured_data",
                    "Regional enrolment trend needs aggregated monthly metrics.",
                    intent="region_enrolment", **({"region_id": region_id}
                                                  if region_id else {})))
                steps.append(_step(
                    "query_structured_data",
                    "Regional investigator capacity trend.",
                    intent="region_capacity", **({"region_id": region_id}
                                                 if region_id else {})))
            else:
                steps.append(_step(
                    "query_structured_data",
                    "Monthly enrolment/cost series per site for trend analysis.",
                    intent="site_trends"))
            if wants_docs:
                steps.append(_step(
                    "search_documents",
                    "Retrieve supporting document passages.",
                    intent="search"))
            return Plan(question_type="mixed", steps=steps,
                        rationale="Combines graph traversal with structured metrics.")

        if wants_rel:
            steps = []
            if DELAYED_RE.search(q):
                steps.append(_step("run_sparql",
                                   "Trials with delayed milestones and their products.",
                                   intent="products_of_delayed_trials"))
            elif entity_ids:
                for entity_id in entity_ids[:2]:
                    steps.append(_step("run_sparql",
                                       f"Graph neighbourhood of {entity_id}.",
                                       intent="entity_neighbours",
                                       entity_id=entity_id))
            else:
                steps.append(_step("run_sparql",
                                   "Delayed milestones with their trials.",
                                   intent="delayed_milestones"))
            if wants_docs:
                steps.append(_step("search_documents",
                                   "Documents that mention the relevant entities.",
                                   intent="search"))
            return Plan(question_type="relationship", steps=steps,
                        rationale="Relationship question -> knowledge graph first.")

        if wants_quant:
            steps = []
            if REGION_RE.search(q):
                steps.append(_step("query_structured_data",
                                   "Regional enrolment trend.",
                                   intent="region_enrolment",
                                   **({"region_id": region_id}
                                      if region_id else {})))
                steps.append(_step("query_structured_data",
                                   "Regional investigator capacity.",
                                   intent="region_capacity",
                                   **({"region_id": region_id}
                                      if region_id else {})))
            elif SAFETY_RE.search(q):
                steps.append(_step("query_structured_data",
                                   "Operational safety events.", intent="safety_events"))
                if entity_ids:
                    steps.append(_step("query_structured_data",
                                       "Site metrics for context.",
                                       intent="site_trends",
                                       site_id=entity_ids[0].split(":", 1)[-1]))
            elif DELAYED_RE.search(q):
                steps.append(_step("query_structured_data",
                                   "Milestone due/completed dates.",
                                   intent="delayed_milestones"))
            else:
                steps.append(_step("query_structured_data",
                                   "Monthly enrolment/cost series per site.",
                                   intent="site_trends"))
                for entity_id in entity_ids[:1]:
                    if entity_id.startswith("site:"):
                        steps.append(_step("query_structured_data",
                                           f"Metrics for {entity_id}.",
                                           intent="site_trends",
                                           site_id=entity_id.split(":", 1)[-1]))
            if COMPARISON_RE.search(q) or "evidence" in q.lower() or "why" in q.lower():
                steps.append(_step("search_documents",
                                   "Supporting narrative from documents.",
                                   intent="search"))
            return Plan(question_type="quantitative", steps=steps,
                        rationale="Quantitative question -> structured metrics.")

        if resolved and LOOKUP_RE.search(q):
            return Plan(question_type="entity_lookup",
                        steps=[_step("get_entity", "Direct entity lookup.",
                                     entity_id=resolved[0].id)],
                        rationale="Entity lookup on a resolved entity.")

        return Plan(
            question_type="semantic",
            steps=[_step("search_documents",
                         "Semantic question -> hybrid document retrieval.",
                         intent="search")],
            rationale="Default: hybrid semantic retrieval.")


class LLMPlanner:
    """LLM-chosen plans, validated; heuristic fallback on any deviation."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._fallback = HeuristicRouter()
        self.last_usage: Usage | None = None  # usage of the last plan call

    def plan(self, question: str, resolved: list[Entity]) -> Plan:
        from nexusgraph.llm.base import ChatMessage, CompletionRequest, extract_json_object
        from nexusgraph.tools.registry import tool_descriptions

        tools = "\n".join(
            f"- {t['name']}: {t['description'].splitlines()[0]}"
            for t in tool_descriptions())
        prompt = (
            "You are the planner of a GraphRAG agent. Choose 1-4 tool steps.\n"
            f"TOOLS:\n{tools}\n\n"
            "Respond ONLY with JSON: {\"question_type\": one of [semantic, "
            "relationship, quantitative, mixed, entity_lookup, unanswerable], "
            "\"steps\": [{\"tool\": <name>, \"intent\": <free text hint>, "
            "\"entity_id\": <optional>}], \"rationale\": \"...\"}\n\n"
            f"QUESTION: {question}"
        )
        try:
            response = self._llm.complete(CompletionRequest(
                messages=[ChatMessage(role="user", content=prompt)],
                task="plan", json_mode=True, max_tokens=512))
            self.last_usage = response.usage
            payload = extract_json_object(response.text)
            plan = self._validate(payload, question, resolved)
            plan.rationale = (plan.rationale or "") + \
                f" [planner: llm:{response.usage.total_tokens}t]"
            return plan
        except Exception as exc:
            logger.warning("LLM planner failed (%s); using heuristic router", exc)
            return self._fallback.plan(question, resolved)

    def _validate(self, payload: dict[str, Any], question: str,
                  resolved: list[Entity]) -> Plan:
        from nexusgraph.tools.registry import REGISTRY

        qtype = payload.get("question_type")
        allowed: tuple[QuestionType, ...] = ("semantic", "relationship",
                                             "quantitative", "mixed",
                                             "entity_lookup", "unanswerable")
        if qtype not in allowed:
            raise ValueError(f"invalid question_type: {qtype}")
        steps: list[PlanStep] = []
        for raw in (payload.get("steps") or [])[:4]:
            tool = raw.get("tool")
            if tool not in REGISTRY:
                raise ValueError(f"unknown tool: {tool}")
            args = {}
            if raw.get("intent"):
                args["intent"] = str(raw["intent"])[:200]
            if raw.get("entity_id"):
                args["entity_id"] = str(raw["entity_id"])[:128]
            if raw.get("site_id"):
                args["site_id"] = str(raw["site_id"])[:64]
            steps.append(PlanStep(tool=cast(ToolName, tool),
                                  rationale=str(raw.get("rationale", "")),
                                  args=args))
        return Plan(question_type=cast(QuestionType, qtype), steps=steps,
                    rationale=str(payload.get("rationale", "")))


def make_planner(llm_provider: str,
                 llm_client: LLMClient | None = None) -> HeuristicRouter | LLMPlanner:
    if llm_provider == "openai-compatible" and llm_client is not None:
        return LLMPlanner(llm_client)
    return HeuristicRouter()


PREFIX_FOR_DOCS = PREFIX_BLOCK  # re-export convenience
