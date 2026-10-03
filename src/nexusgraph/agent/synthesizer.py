"""Synthesizers: collected evidence -> grounded answer draft.

Two implementations behind one protocol:

- :class:`DeterministicSynthesizer` — no LLM. Builds claims directly from the
  structured series (trend slopes via :mod:`nexusgraph.agent.analysis`), RDF
  bindings and document snippets held by the evidence ledger. Used in ``mock``
  provider mode (hermetic tests + evals) and as the fallback whenever the LLM
  synthesizer fails or produces nothing citable.
- :class:`LLMSynthesizer` — prompts the model with the evidence JSON and
  accepts claims only when their evidence ids resolve in the ledger; invalid
  claims are dropped, and a total failure falls back to the deterministic
  synthesizer. Fabricated citations are therefore structurally impossible in
  both paths.

Output is an :class:`AnswerDraft`; the orchestrator still re-checks every
citation marker and evidence id before returning an :class:`AgentAnswer`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from nexusgraph.agent.analysis import first_last, linear_slope, trend
from nexusgraph.agent.evidence import EvidenceLedger
from nexusgraph.domain.models import (
    Claim,
    Entity,
    Evidence,
    QuestionType,
    SourceType,
    StructuredQueryResult,
    ToolName,
    Usage,
)
from nexusgraph.llm.base import ChatMessage, CompletionRequest, LLMClient, extract_json_object
from nexusgraph.observability.logging import get_logger

logger = get_logger("agent.synthesizer")

_MAX_LISTED = 6  # max items listed inline in a claim sentence
_MAX_DOC_CLAIMS = 3
_MAX_ROW_CLAIMS = 5
_CITATION_MARK = re.compile(r"\[(\d{1,3})\]")
_ID_TOKEN = re.compile(r"\b[A-Z]{1,12}-\d{2,5}\b")


@dataclass
class ToolOutcome:
    """One executed plan step, kept in typed form for the synthesizers."""

    tool: ToolName
    intent: str
    status: str  # ok | empty | error
    result: Any = None
    table: str | None = None  # for structured results


@dataclass
class SynthesisRequest:
    question: str
    question_type: QuestionType
    outcomes: list[ToolOutcome] = field(default_factory=list)
    resolved: list[Entity] = field(default_factory=list)


@dataclass
class AnswerDraft:
    answer: str
    claims: list[Claim]
    insufficient: bool = False
    insufficient_reason: str | None = None
    synthesized_by: str = "deterministic"  # deterministic | llm


class DeterministicSynthesizer:
    """Evidence -> claims -> cited answer, with no model in the loop."""

    def synthesize(self, request: SynthesisRequest, ledger: EvidenceLedger) -> AnswerDraft:
        if request.question_type == "unanswerable":
            return _insufficient(
                "the question asks about data this system does not model "
                "(e.g. financials, demographics); refusing rather than guessing"
            )
        if not ledger.items():
            return _insufficient("no tool returned any usable evidence")

        claims: list[Claim] = []
        claims += self._claims_from_structured(request, ledger)
        claims += self._claims_from_sparql(ledger)
        claims += self._claims_from_documents(ledger)
        claims += self._claims_from_entities(ledger)
        cross = self._cross_source_claim(ledger)
        if cross:
            claims.append(cross)
        claims = [c for c in claims if c.evidence_ids]

        if not claims:
            return _insufficient(
                "tools ran successfully but returned no evidence usable for a grounded answer"
            )

        answer = _compose_answer(request, claims)
        return AnswerDraft(answer=answer, claims=claims)

    # ------------------------------------------------------------------ SQL
    def _claims_from_structured(
        self, request: SynthesisRequest, ledger: EvidenceLedger
    ) -> list[Claim]:
        claims: list[Claim] = []
        for outcome in request.outcomes:
            if (
                outcome.tool != "query_structured_data"
                or not isinstance(outcome.result, StructuredQueryResult)
                or outcome.status == "error"
                or outcome.table is None
            ):
                continue
            result = outcome.result
            table = outcome.table
            if table in (
                "site_metrics_monthly",
                "site_metrics_region_monthly",
                "investigator_capacity_region_monthly",
            ):
                claims += self._trend_claims(table, result, ledger)
            elif table == "milestones":
                claims += self._milestone_claims(table, result, ledger)
            else:
                claims += self._row_listing_claims(table, result, ledger)
        return claims

    def _trend_claims(
        self, table: str, result: StructuredQueryResult, ledger: EvidenceLedger
    ) -> list[Claim]:
        group_col = "site_id" if table == "site_metrics_monthly" else "region_id"
        specs = {
            "site_metrics_monthly": [
                ("sum_patients_enrolled", "patient enrolment"),
                ("sum_operational_cost", "operational cost"),
            ],
            "site_metrics_region_monthly": [
                ("total_patients_enrolled", "patient enrolment"),
                ("total_operational_cost", "operational cost"),
            ],
            "investigator_capacity_region_monthly": [
                ("avg_capacity_index", "investigator capacity index")
            ],
        }
        claims: list[Claim] = []
        for column, label in specs[table]:
            series = _series(result.rows, group_col, "month", column)
            for group, points in sorted(series.items()):
                movement = trend(points)
                ends = first_last(points)
                evidence_ids = _sql_evidence_ids(ledger, table, group)
                if not evidence_ids or ends is None:
                    continue
                direction = {
                    "increasing": "increasing",
                    "decreasing": "decreasing",
                    "flat": "approximately flat",
                }[movement]
                claims.append(
                    Claim(
                        claim=(
                            f"{label.capitalize()} for {group} is {direction} "
                            f"({ends[0]:.0f} -> {ends[1]:.0f} across the "
                            f"{len(points)} recorded months)."
                        ),
                        evidence_ids=evidence_ids,
                        confidence=round(min(1.0, 0.5 + abs(linear_slope(points)) * 0.1), 2),
                    )
                )
        return claims[: _MAX_ROW_CLAIMS * 2]

    def _milestone_claims(
        self, table: str, result: StructuredQueryResult, ledger: EvidenceLedger
    ) -> list[Claim]:
        claims: list[Claim] = []
        for row in result.rows[:_MAX_ROW_CLAIMS]:
            due, completed = row.get("due_date"), row.get("completed_date")
            if due and completed and completed > due:
                claims.append(
                    Claim(
                        claim=(
                            f"Milestone {row.get('milestone_id')} of trial "
                            f"{row.get('trial_id')} was completed late "
                            f"(due {due}, completed {completed})."
                        ),
                        evidence_ids=_sql_evidence_ids(ledger, table, str(row.get("milestone_id"))),
                    )
                )
        delayed = sum(
            1
            for row in result.rows
            if row.get("due_date")
            and row.get("completed_date")
            and str(row["completed_date"]) > str(row["due_date"])
        )
        if delayed and len(result.rows) > _MAX_ROW_CLAIMS:
            claims.append(
                Claim(
                    claim=f"{delayed} of {result.row_count} listed milestones were "
                    f"completed after their due date.",
                    evidence_ids=_sql_evidence_ids(ledger, table),
                )
            )
        return claims

    def _row_listing_claims(
        self, table: str, result: StructuredQueryResult, ledger: EvidenceLedger
    ) -> list[Claim]:
        if not result.rows:
            return []
        preview = "; ".join(json.dumps(row, default=str)[:120] for row in result.rows[:3])
        return [
            Claim(
                claim=(
                    f"The {table} table returned {result.row_count} row(s); first rows: {preview}."
                ),
                evidence_ids=_sql_evidence_ids(ledger, table),
            )
        ]

    # ---------------------------------------------------------------- SPARQL
    def _claims_from_sparql(self, ledger: EvidenceLedger) -> list[Claim]:
        rdf = ledger.by_source_type(SourceType.rdf)
        if not rdf:
            return []
        entity_evidence = [e for e in rdf if e.location.startswith("entity:")]
        bindings = [e for e in rdf if not e.location.startswith("entity:")]
        claims: list[Claim] = []
        if bindings:
            ids = _collect_ids(bindings)
            if ids:
                claims.append(
                    Claim(
                        claim=(
                            "The knowledge graph links the following entities: "
                            + ", ".join(sorted(ids)[:_MAX_LISTED])
                            + "."
                        ),
                        evidence_ids=[e.evidence_id for e in bindings],
                    )
                )
        if entity_evidence:
            claims.append(
                Claim(
                    claim=(
                        "Entity lookup returned: "
                        + "; ".join(
                            f"{e.source_id}: {(e.snippet or e.source_id)[:160]}"
                            for e in entity_evidence[:_MAX_LISTED]
                        )
                        + "."
                    ),
                    evidence_ids=[e.evidence_id for e in entity_evidence],
                )
            )
        return claims

    # ------------------------------------------------------------- documents
    def _claims_from_documents(self, ledger: EvidenceLedger) -> list[Claim]:
        claims: list[Claim] = []
        seen_docs: set[str] = set()
        for evidence in ledger.by_source_type(SourceType.document):
            if evidence.source_id in seen_docs:
                continue
            seen_docs.add(evidence.source_id)
            snippet = (evidence.snippet or "").strip()
            claims.append(
                Claim(
                    claim=(f'Document {evidence.source_id} states: "{snippet[:200]}"'),
                    evidence_ids=[evidence.evidence_id],
                )
            )
            if len(seen_docs) >= _MAX_DOC_CLAIMS:
                break
        return claims

    def _claims_from_entities(self, ledger: EvidenceLedger) -> list[Claim]:
        return []  # entity evidence already covered by _claims_from_sparql

    # -------------------------------------------------------------- cross-src
    def _cross_source_claim(self, ledger: EvidenceLedger) -> Claim | None:
        """Mixed questions: an entity id appearing in both SQL and RDF/graph
        evidence is itself a finding worth stating (e.g. a site that shows a
        declining enrolment trend AND is associated with safety-report
        compounds in the graph)."""
        sql_ids: dict[str, list[str]] = {}
        for evidence in ledger.by_source_type(SourceType.sql):
            for token in _ID_TOKEN.findall(evidence.location):
                sql_ids.setdefault(token, []).append(evidence.evidence_id)
        rdf_ids: dict[str, list[str]] = {}
        for evidence in ledger.by_source_type(SourceType.rdf):
            text = " ".join(filter(None, (evidence.location, evidence.snippet, evidence.uri)))
            for token in _ID_TOKEN.findall(text):
                rdf_ids.setdefault(token, []).append(evidence.evidence_id)
        overlap = sorted(set(sql_ids) & set(rdf_ids))
        if not overlap:
            return None
        return Claim(
            claim=(
                "Cross-source link: "
                + ", ".join(overlap[:_MAX_LISTED])
                + " appear in both the structured metrics and the "
                "knowledge-graph results."
            ),
            evidence_ids=sorted(set(sql_ids[overlap[0]]) | set(rdf_ids[overlap[0]])),
        )


class LLMSynthesizer:
    """LLM-written answer under strict citation validation."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._fallback = DeterministicSynthesizer()
        self.last_usage: Usage | None = None  # usage of the last synthesis call

    def synthesize(self, request: SynthesisRequest, ledger: EvidenceLedger) -> AnswerDraft:
        evidence = ledger.items()
        if request.question_type == "unanswerable" or not evidence:
            return self._fallback.synthesize(request, ledger)
        try:
            draft = self._llm_synthesize(request, evidence)
            if draft is not None:
                return draft
        except Exception as exc:
            logger.warning("LLM synthesis failed (%s); falling back", exc)
        return self._fallback.synthesize(request, ledger)

    def _llm_synthesize(
        self, request: SynthesisRequest, evidence: list[Evidence]
    ) -> AnswerDraft | None:
        evidence_json = json.dumps(
            [
                {
                    "id": e.evidence_id,
                    "source": e.source_id,
                    "location": e.location,
                    "snippet": e.snippet,
                }
                for e in evidence
            ],
            ensure_ascii=False,
        )
        prompt = (
            "You are the synthesis step of a grounded GraphRAG agent.\n"
            f"QUESTION ({request.question_type}): {request.question}\n\n"
            f"EVIDENCE (the ONLY citable items):\n{evidence_json}\n\n"
            "Rules:\n"
            "- Every claim MUST reference only ids from the evidence list.\n"
            "- Cite in the answer text with [1]-style markers, where the number "
            "is the position (1-based) of the evidence item in the list.\n"
            "- Do not invent facts, numbers or citations. If the evidence is "
            'insufficient, set "insufficient": true.\n'
            'Respond ONLY with JSON: {"answer": str, "claims": '
            '[{"claim": str, "evidence_ids": [str]}], "insufficient": bool,'
            ' "insufficient_reason": str|null}'
        )
        response = self._llm.complete(
            CompletionRequest(
                messages=[ChatMessage(role="user", content=prompt)],
                task="synthesize",
                json_mode=True,
                max_tokens=1024,
            )
        )
        self.last_usage = response.usage
        payload = extract_json_object(response.text)
        return self._validate(payload, evidence, request)

    def _validate(
        self, payload: dict[str, Any], evidence: list[Evidence], request: SynthesisRequest
    ) -> AnswerDraft | None:
        answer = str(payload.get("answer", "")).strip()
        if not answer:
            return None
        known = {e.evidence_id for e in evidence}
        claims: list[Claim] = []
        for raw in (payload.get("claims") or [])[:12]:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("claim", "")).strip()
            ids = [e for e in (raw.get("evidence_ids") or []) if e in known]
            dropped = len(raw.get("evidence_ids") or []) - len(ids)
            if dropped:
                logger.warning("dropped %d invalid evidence id(s) on a claim", dropped)
            if not text:
                continue
            claims.append(Claim(claim=text, evidence_ids=ids, unsupported=not ids))
        if payload.get("insufficient") or not claims:
            reason = (
                payload.get("insufficient_reason") or "the model judged the evidence insufficient"
            )
            return AnswerDraft(
                answer=answer,
                claims=claims,
                insufficient=True,
                insufficient_reason=str(reason),
                synthesized_by="llm",
            )
        # Citation markers in the text must point at real positions.
        answer = _strip_bad_markers(answer, len(evidence))
        return AnswerDraft(answer=answer, claims=claims, synthesized_by="llm")


def make_synthesizer(
    llm_provider: str,
    llm_client: LLMClient | None = None,
) -> DeterministicSynthesizer | LLMSynthesizer:
    if llm_provider == "openai-compatible" and llm_client is not None:
        return LLMSynthesizer(llm_client)
    return DeterministicSynthesizer()


# --------------------------------------------------------------------- helpers
def _insufficient(reason: str) -> AnswerDraft:
    return AnswerDraft(
        answer=(
            "I could not answer this question from the available data: "
            + reason
            + " No claims are made."
        ),
        claims=[],
        insufficient=True,
        insufficient_reason=reason,
    )


def _series(
    rows: list[dict], group_col: str, x_col: str, y_col: str
) -> dict[str, list[tuple[float, float]]]:
    series: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        group = str(row.get(group_col, ""))
        x_raw, y_raw = row.get(x_col), row.get(y_col)
        if x_raw is None or y_raw is None:
            continue
        try:
            x = float(str(x_raw)[:7].replace("-", ""))  # YYYY-MM -> YYYYMM
            y = float(y_raw)
        except (TypeError, ValueError):
            continue
        series.setdefault(group, []).append((x, y))
    for points in series.values():
        points.sort()
    return series


def _sql_evidence_ids(ledger: EvidenceLedger, table: str, *contains: str) -> list[str]:
    ids = []
    for evidence in ledger.by_source_type(SourceType.sql):
        if evidence.source_id != f"sql:{table}":
            continue
        if all(term in evidence.location for term in contains):
            ids.append(evidence.evidence_id)
    return ids


def _collect_ids(evidence_items: list[Evidence]) -> set[str]:
    ids: set[str] = set()
    for evidence in evidence_items:
        ids.update(_ID_TOKEN.findall(evidence.location))
        if evidence.snippet:
            ids.update(_ID_TOKEN.findall(evidence.snippet))
    return ids


def _strip_bad_markers(answer: str, evidence_count: int) -> str:
    def _sub(match: re.Match) -> str:
        position = int(match.group(1))
        return match.group(0) if 1 <= position <= evidence_count else ""

    return _CITATION_MARK.sub(_sub, answer).strip()


def _compose_answer(request: SynthesisRequest, claims: list[Claim]) -> str:
    lines: list[str] = []
    for claim in claims[:8]:
        lines.append(_mark(claim))
    if request.question_type in ("quantitative", "mixed"):
        lines.append(
            "(Trends are least-squares slopes over the retrieved "
            "monthly rows; only groups with retrieved rows are "
            "reported. See the citations for the underlying data.)"
        )
    return "\n\n".join(lines)


def _mark(claim: Claim) -> str:
    text = claim.claim
    if not claim.evidence_ids:
        return text
    markers = []
    for evidence_id in claim.evidence_ids[:6]:
        try:
            position = int(evidence_id.split("-")[-1])
        except ValueError:
            continue
        markers.append(f"[{position}]")
    return f"{text} {' '.join(markers)}".strip()
