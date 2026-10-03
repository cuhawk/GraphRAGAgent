"""Agent orchestrator: plan -> guarded tool execution -> evidence -> synthesis.

The orchestrator is the only component that mints :class:`AgentAnswer` objects.
It expands planner *intents* into concrete guarded tool arguments (templated
SPARQL, typed QuerySpecs, retrieval args), runs each tool under the shared
tool-call budget with a trace span, converts results into ledger evidence, and
finally synthesizes a grounded answer whose citations are re-verified against
the ledger before returning.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from nexusgraph.agent.evidence import EvidenceLedger
from nexusgraph.agent.planner import make_planner
from nexusgraph.agent.query_specs import (
    delayed_milestones,
    region_capacity_monthly,
    region_enrolment_monthly,
    safety_events,
    site_monthly_metrics,
    trial_rows,
)
from nexusgraph.agent.resolver import QuestionEntityResolver
from nexusgraph.agent.sparql_templates import (
    compounds_with_safety_reports_and_sites,
    delayed_milestones_with_trials,
    documents_mentioning,
    entity_neighbours,
    products_of_delayed_trials,
    safety_events_at_site,
    sites_of_trial,
    trials_of_compound,
)
from nexusgraph.agent.synthesizer import (
    AnswerDraft,
    DeterministicSynthesizer,
    LLMSynthesizer,
    SynthesisRequest,
    ToolOutcome,
    _strip_bad_markers,
)
from nexusgraph.config import Settings
from nexusgraph.domain.models import (
    AgentAnswer,
    Claim,
    Entity,
    PlanStep,
    QuerySpec,
    QuestionType,
    SourceType,
    StructuredQueryResult,
    ToolRun,
    Usage,
)
from nexusgraph.llm.base import LLMClient
from nexusgraph.observability.logging import get_logger
from nexusgraph.runtime import Runtime
from nexusgraph.tools.base import ToolBudget, ToolContext, ToolError
from nexusgraph.tools.registry import REGISTRY
from nexusgraph.tools.schemas import (
    GetEntityArgs,
    GetRelationshipsArgs,
    QueryStructuredArgs,
    RunSparqlArgs,
    SearchDocumentsArgs,
)
from nexusgraph.utils import ToolTimeoutError

logger = get_logger("agent.orchestrator")


class AgentOrchestrator:
    """One instance per app/CLI process; ``run`` is re-entrant."""

    def __init__(self, runtime: Runtime,
                 llm_client: LLMClient | None = None) -> None:
        self.runtime = runtime
        self.settings: Settings = runtime.settings
        self.limits = runtime.settings.limits
        self._llm = llm_client
        self._planner = make_planner(self.settings.llm.provider, llm_client)
        self._synthesizer: DeterministicSynthesizer | LLMSynthesizer = \
            DeterministicSynthesizer()
        if self.settings.llm.provider == "openai-compatible" and llm_client is not None:
            self._synthesizer = LLMSynthesizer(llm_client)
        self._resolver: QuestionEntityResolver | None = None

    # ------------------------------------------------------------------ API
    def refresh(self) -> None:
        """Rebuild the question-time entity resolver (after ingestion)."""
        self._resolver = None

    def run(self, question: str,
            progress_cb: Callable[[str, dict[str, Any]], None] | None = None
            ) -> AgentAnswer:
        """Answer ``question``; optionally report progress events.

        ``progress_cb(event_name, payload)`` is invoked from the caller's
        thread (before the answer returns) at plan time, after each tool
        step and after synthesis - the streaming endpoint's transport.
        """
        question = (question or "").strip()
        if not question:
            raise ValueError("question must not be empty")
        if len(question) > self.limits.max_input_chars:
            raise ValueError(
                f"question exceeds the {self.limits.max_input_chars}-character limit")

        def emit(event: str, payload: dict[str, Any]) -> None:
            if progress_cb is not None:
                try:
                    progress_cb(event, payload)
                except Exception:  # pragma: no cover - transport must not break runs
                    logger.exception("progress callback failed")

        started = time.perf_counter()
        trace = self.runtime.tracer.start_trace()
        trace.set_question(question)
        ledger = EvidenceLedger()
        budget = ToolBudget(self.limits.max_tool_calls_per_run)
        ctx = ToolContext(runtime=self.runtime, limits=self.limits,
                          budget=budget, trace=trace,
                          known_evidence_ids=ledger.ids())
        outcomes: list[ToolOutcome] = []
        tool_runs: list[ToolRun] = []
        plan_rationale = ""
        question_type: QuestionType = "semantic"
        usage = Usage()

        try:
            with trace.span("resolve_entities"):
                resolved = self._question_entities(question)
            with trace.span("plan", entities=[e.id for e in resolved]):
                plan = self._planner.plan(question, resolved)
            usage.add(_planner_usage(self._planner))
            question_type = plan.question_type
            plan_rationale = plan.rationale
            trace.set_attributes(question_type=question_type,
                                 planned_steps=len(plan.steps))
            emit("plan", {"question_type": question_type,
                          "steps": [{"tool": s.tool,
                                     "intent": s.args.get("intent", "")}
                                    for s in plan.steps]})

            with trace.span("execute_plan"):
                for step in plan.steps:
                    if budget.used >= self.limits.max_tool_calls_per_run:
                        break
                    tool_run, outcome = self._execute_step(
                        step, ctx, ledger, resolved, question)
                    tool_runs.append(tool_run)
                    outcomes.append(outcome)
                    emit("tool", tool_run.model_dump(mode="json"))

            with trace.span("synthesize"):
                request = SynthesisRequest(
                    question=question, question_type=question_type,
                    outcomes=outcomes, resolved=resolved)
                draft = self._synthesizer.synthesize(request, ledger)
            usage.add(_synthesizer_usage(self._synthesizer))
            emit("synthesis", {"insufficient": draft.insufficient,
                               "claims": len(draft.claims),
                               "evidence": len(ledger.items())})

            claims, answer_text = self._verify(draft, ledger)
        except Exception as exc:
            trace.finish("error", f"{type(exc).__name__}: {exc}")
            self.runtime.trace_sink.save(trace.record)
            raise
        trace.finish("ok")
        trace.set_attributes(claims=len(claims), evidence=len(ledger.items()),
                             insufficient=draft.insufficient,
                             tool_calls=budget.used)
        self.runtime.trace_sink.save(trace.record)

        return AgentAnswer(
            question=question,
            answer=answer_text,
            question_type=question_type,
            claims=claims,
            evidence=ledger.items(),
            tools_used=tool_runs,
            plan_rationale=plan_rationale,
            trace_id=trace.trace_id,
            insufficient=draft.insufficient,
            insufficient_reason=draft.insufficient_reason,
            usage=usage,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    # ----------------------------------------------------------- resolution
    def _question_entities(self, question: str) -> list[Entity]:
        if self._resolver is None:
            names = self.runtime.entities.all_names(limit=1000)
            names += self._dataset_aliases()
            self._resolver = QuestionEntityResolver(names)
        return self._resolver.resolve(question)

    def _dataset_aliases(self) -> list[tuple[str, str]]:
        """Surface forms -> entity ids generated with the corpus (e.g.
        'Site A' -> site:S-1001); complements canonical entity names."""
        import json

        path = self.runtime.dataset_dir / "aliases.json"
        try:
            with path.open(encoding="utf-8") as fh:
                return [(str(k), str(v)) for k, v in json.load(fh).items()]
        except (OSError, ValueError):
            return []

    # ------------------------------------------------------------- execution
    def _execute_step(self, step: PlanStep, ctx: ToolContext,
                      ledger: EvidenceLedger, resolved: list[Entity],
                      question: str) -> tuple[ToolRun, ToolOutcome]:
        args_summary = {k: v for k, v in step.args.items() if k != "query"}
        try:
            ctx.budget.acquire(step.tool)
        except ToolError as exc:
            return (ToolRun(tool=step.tool, args=args_summary,
                            status="error", error=str(exc)),
                    ToolOutcome(tool=step.tool, intent=step.args.get("intent", ""),
                                status="error"))
        started = time.perf_counter()
        with (ctx.trace.span(f"tool:{step.tool}",
                             intent=step.args.get("intent", "")) if ctx.trace
              else _NullSpan()):
            try:
                outcome = self._invoke(step, ctx, resolved, question)
                status = outcome.status
            except (ToolError, ToolTimeoutError, ValueError) as exc:
                logger.warning("tool %s failed: %s", step.tool, exc)
                status = "error"
                outcome = ToolOutcome(tool=step.tool,
                                      intent=step.args.get("intent", ""),
                                      status="error")
            duration = round((time.perf_counter() - started) * 1000, 1)
            self._to_evidence(outcome, ledger)
            ctx.known_evidence_ids = ledger.ids()
        return (ToolRun(tool=step.tool, args=args_summary, status=status,
                        duration_ms=duration,
                        result_count=self._result_count(outcome)),
                outcome)

    def _invoke(self, step: PlanStep, ctx: ToolContext, resolved: list[Entity],
                question: str) -> ToolOutcome:
        intent = str(step.args.get("intent", ""))
        tool = step.tool
        if tool == "search_documents":
            args = SearchDocumentsArgs(query=question, k=self.limits.retrieval_k)
            hits = REGISTRY[tool].handler(ctx, args)
            return ToolOutcome(tool=tool, intent=intent,
                               status="ok" if hits else "empty", result=hits)
        if tool == "run_sparql":
            query, named = self._sparql_for(intent, step.args, resolved)
            sparql_args = RunSparqlArgs(query=query, include_named_graphs=named)
            result = REGISTRY[tool].handler(ctx, sparql_args)
            return ToolOutcome(tool=tool, intent=intent,
                               status="ok" if result.rows else "empty",
                               result=result)
        if tool == "query_structured_data":
            spec, table = self._spec_for(intent, step.args, resolved)
            structured_args = QueryStructuredArgs(spec=spec)
            result = REGISTRY[tool].handler(ctx, structured_args)
            return ToolOutcome(tool=tool, intent=intent,
                               status="ok" if result.rows else "empty",
                               result=result, table=table)
        if tool == "get_entity":
            entity_id = step.args.get("entity_id") \
                or (resolved[0].id if resolved else None)
            if not entity_id:
                return ToolOutcome(tool=tool, intent=intent, status="empty")
            entity_args = GetEntityArgs(entity_id=entity_id)
            detail = REGISTRY[tool].handler(ctx, entity_args)
            return ToolOutcome(tool=tool, intent=intent,
                               status="ok" if detail else "empty", result=detail)
        if tool == "get_relationships":
            entity_id = step.args.get("entity_id") \
                or (resolved[0].id if resolved else None)
            if not entity_id:
                return ToolOutcome(tool=tool, intent=intent, status="empty")
            rel_args = GetRelationshipsArgs(
                entity_id=entity_id, relation=step.args.get("relation"))
            rels = REGISTRY[tool].handler(ctx, rel_args)
            return ToolOutcome(tool=tool, intent=intent,
                               status="ok" if rels else "empty", result=rels)
        if tool == "retrieve_document":
            from nexusgraph.tools.schemas import RetrieveDocumentArgs

            document_id = step.args.get("document_id")
            if not document_id:
                return ToolOutcome(tool=tool, intent=intent, status="empty")
            detail = REGISTRY[tool].handler(
                ctx, RetrieveDocumentArgs(document_id=document_id))
            return ToolOutcome(tool=tool, intent=intent,
                               status="ok" if detail else "empty", result=detail)
        # verify_claim is reserved for the synthesis/citation path.
        return ToolOutcome(tool=tool, intent=intent, status="empty")

    # -------------------------------------------------- intent -> guarded args
    def _sparql_for(self, intent: str, args: dict, resolved: list[Entity],
                    ) -> tuple[str, bool]:
        entity_id = args.get("entity_id") or (resolved[0].id if resolved else None)
        if intent == "compounds_with_safety_sites":
            return compounds_with_safety_reports_and_sites(), False
        if intent == "products_of_delayed_trials":
            return products_of_delayed_trials(), False
        if intent == "delayed_milestones":
            return delayed_milestones_with_trials(), False
        if intent == "documents_mentioning":
            ids = [e.id for e in resolved] or ["site:S-1001"]
            return documents_mentioning(ids), True
        if intent == "safety_events" and entity_id and entity_id.startswith("site:"):
            return safety_events_at_site(entity_id), False
        if intent == "sites_of_trial" and entity_id:
            return sites_of_trial(entity_id), False
        if intent == "trials_of_compound" and entity_id:
            return trials_of_compound(entity_id), False
        if entity_id:
            return entity_neighbours(entity_id), False
        return delayed_milestones_with_trials(), False

    def _spec_for(self, intent: str, args: dict,
                  resolved: list[Entity]) -> tuple[QuerySpec, str]:
        site_id = next((e.id.split(":", 1)[1] for e in resolved
                        if e.id.startswith("site:")), None)
        region_id = next((e.id.split(":", 1)[1] for e in resolved
                          if e.id.startswith("region:")), None)
        site_id = args.get("site_id") or site_id
        region_id = args.get("region_id") or region_id
        if intent == "region_enrolment":
            return region_enrolment_monthly(region_id), "site_metrics_region_monthly"
        if intent == "region_capacity":
            return (region_capacity_monthly(region_id),
                    "investigator_capacity_region_monthly")
        if intent == "site_trends":
            return site_monthly_metrics(site_id=site_id), "site_metrics_monthly"
        if intent == "safety_events":
            return safety_events(site_id), "safety_events"
        if intent == "delayed_milestones":
            return delayed_milestones(), "milestones"
        if intent == "trial_rows":
            return trial_rows(args.get("trial_id")), "trials"
        return site_monthly_metrics(site_id=site_id), "site_metrics_monthly"

    # --------------------------------------------------------- evidence bridge
    def _to_evidence(self, outcome: ToolOutcome, ledger: EvidenceLedger) -> None:
        result = outcome.result
        if result is None or outcome.status == "error":
            return
        if isinstance(result, StructuredQueryResult):
            ledger.add_structured(result, outcome.table or "unknown")
        elif isinstance(result, list):
            if result and hasattr(result[0], "chunk_id"):  # SearchHit
                ledger.add_search_hits(result)
            else:  # Relationship list
                for rel in result:
                    ledger._add(
                        source_id=f"rel:{rel.source_id}->{rel.relation}"
                                  f"->{rel.target_id}",
                        source_type=SourceType.rdf,
                        location=f"{rel.source_id} -{rel.relation}-> "
                                 f"{rel.target_id}")
        elif hasattr(result, "rows"):  # SparqlResult
            ledger.add_sparql(result)
        elif hasattr(result, "entity"):  # EntityDetail
            ledger.add_entity(result)
        elif hasattr(result, "document"):  # DocumentDetail
            ledger.add_document(result)

    @staticmethod
    def _result_count(outcome: ToolOutcome) -> int:
        result = outcome.result
        if result is None or outcome.status == "error":
            return 0
        if isinstance(result, list):
            return len(result)
        if hasattr(result, "rows"):
            return result.row_count
        return 1

    # ------------------------------------------------------------ citations
    def _verify(self, draft: AnswerDraft,
                ledger: EvidenceLedger) -> tuple[list[Claim], str]:
        known = ledger.ids()
        verified: list[Claim] = []
        for claim in draft.claims:
            valid = [e for e in claim.evidence_ids if e in known]
            if len(valid) != len(claim.evidence_ids):
                logger.warning("claim dropped %d invalid evidence id(s)",
                               len(claim.evidence_ids) - len(valid))
            verified.append(claim.model_copy(
                update={"evidence_ids": valid,
                        "unsupported": not valid or claim.unsupported}))
        answer = _strip_bad_markers(draft.answer, len(ledger.items()))
        return verified, answer


def _planner_usage(planner: object) -> Usage:
    last = getattr(planner, "last_usage", None)
    return last if last is not None else Usage()


def _synthesizer_usage(synthesizer: object) -> Usage:
    last = getattr(synthesizer, "last_usage", None)
    return last if last is not None else Usage()


class _NullSpan:
    """Context-manager shim when a tool has no trace recorder."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> None:
        return None
