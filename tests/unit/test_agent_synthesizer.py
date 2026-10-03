"""Synthesizer unit tests: honest claims, citation validation, fallbacks."""

from __future__ import annotations

import pytest

from nexusgraph.agent.evidence import EvidenceLedger
from nexusgraph.agent.synthesizer import (
    DeterministicSynthesizer,
    LLMSynthesizer,
    SynthesisRequest,
    ToolOutcome,
)
from nexusgraph.domain.models import (
    SearchHit,
    SparqlResult,
    StructuredQueryResult,
)
from nexusgraph.llm.mock import MockLLMClient

DET = DeterministicSynthesizer()


def structured(table: str, rows: list[dict]) -> ToolOutcome:
    result = StructuredQueryResult(
        executed_sql=f"SELECT ... FROM {table}",
        columns=list(rows[0]) if rows else [],
        rows=rows,
        row_count=len(rows),
    )
    return ToolOutcome(
        tool="query_structured_data", intent="site_trends", status="ok", result=result, table=table
    )


def run(request: SynthesisRequest, ledger: EvidenceLedger):
    return DET.synthesize(request, ledger)


def test_trend_claim_for_declining_site():
    ledger = EvidenceLedger()
    outcome = structured(
        "site_metrics_monthly",
        [
            {
                "site_id": "S-1001",
                "month": "2024-01",
                "sum_patients_enrolled": 12,
                "sum_operational_cost": 100,
            },
            {
                "site_id": "S-1001",
                "month": "2024-02",
                "sum_patients_enrolled": 9,
                "sum_operational_cost": 110,
            },
            {
                "site_id": "S-1001",
                "month": "2024-03",
                "sum_patients_enrolled": 5,
                "sum_operational_cost": 130,
            },
        ],
    )
    ledger.add_structured(outcome.result, "site_metrics_monthly")
    draft = run(
        SynthesisRequest(question="Trends?", question_type="quantitative", outcomes=[outcome]),
        ledger,
    )
    assert not draft.insufficient
    enrolment = next(c for c in draft.claims if "enrolment" in c.claim.lower())
    assert "decreasing" in enrolment.claim
    assert enrolment.evidence_ids  # cited
    assert all(e.startswith("ev-") for e in enrolment.evidence_ids)
    assert "[1]" in draft.answer or "[2]" in draft.answer


def test_no_evidence_is_insufficient():
    draft = run(SynthesisRequest(question="Anything", question_type="semantic"), EvidenceLedger())
    assert draft.insufficient
    assert draft.claims == []


def test_unanswerable_refuses_without_tools():
    ledger = EvidenceLedger()
    ledger.add_search_hits(
        [SearchHit(chunk_id="d#chunk-1", document_id="D-1", score=0.9, text="some text")]
    )
    draft = run(SynthesisRequest(question="Market share?", question_type="unanswerable"), ledger)
    assert draft.insufficient
    assert draft.claims == []


def test_document_claims_cite_their_evidence():
    ledger = EvidenceLedger()
    ledger.add_search_hits(
        [
            SearchHit(
                chunk_id="D-9001#chunk-0",
                document_id="D-9001",
                score=0.9,
                text="Enrolment at Site A slowed in March.",
            ),
        ]
    )
    draft = run(
        SynthesisRequest(question="What happened at Site A?", question_type="semantic"), ledger
    )
    assert any("D-9001" in c.claim for c in draft.claims)
    assert all(c.evidence_ids for c in draft.claims)
    assert all(c.evidence_ids[0] in ledger.ids() for c in draft.claims)


def test_cross_source_claim_when_id_in_both_sources():
    ledger = EvidenceLedger()
    outcome = structured(
        "site_metrics_monthly",
        [
            {
                "site_id": "S-1001",
                "month": "2024-01",
                "sum_patients_enrolled": 12,
                "sum_operational_cost": 100,
            },
        ],
    )
    ledger.add_structured(outcome.result, "site_metrics_monthly")
    ledger.add_sparql(
        SparqlResult(
            query="SELECT ...",
            variables=["site", "name"],
            rows=[{"site": "https://nexusgraph.dev/data/Site/S-1001", "name": "Site A"}],
            row_count=1,
        )
    )
    draft = run(
        SynthesisRequest(
            question="Why is enrolment falling at Site A?",
            question_type="mixed",
            outcomes=[outcome],
        ),
        ledger,
    )
    cross = [c for c in draft.claims if "Cross-source" in c.claim]
    assert cross and "S-1001" in cross[0].claim
    assert cross[0].evidence_ids


def test_llm_synthesizer_drops_invalid_evidence_ids():
    ledger = EvidenceLedger()
    ledger.add_search_hits(
        [SearchHit(chunk_id="D-1#chunk-0", document_id="D-1", score=0.9, text="text")]
    )
    llm = MockLLMClient(
        responses={
            "synthesize": (
                '{"answer": "The site is fine [1].", "claims": ['
                '{"claim": "The site is fine", "evidence_ids": ["ev-0001", "ev-9999"]},'
                '{"claim": "Fabricated", "evidence_ids": ["ev-4242"]}], '
                '"insufficient": false}'
            )
        }
    )
    draft = LLMSynthesizer(llm).synthesize(
        SynthesisRequest(question="q", question_type="semantic"), ledger
    )
    assert draft.synthesized_by == "llm"
    assert all(e in ledger.ids() for c in draft.claims for e in c.evidence_ids)
    fabricated = next(c for c in draft.claims if "Fabricated" in c.claim)
    assert fabricated.unsupported  # kept but flagged, cites nothing real


def test_llm_synthesizer_falls_back_on_bad_json():
    ledger = EvidenceLedger()
    ledger.add_search_hits(
        [SearchHit(chunk_id="D-1#chunk-0", document_id="D-1", score=0.9, text="text")]
    )
    llm = MockLLMClient(responses={"synthesize": "garbage {"})
    draft = LLMSynthesizer(llm).synthesize(
        SynthesisRequest(question="q", question_type="semantic"), ledger
    )
    assert draft.synthesized_by == "deterministic"


def test_llm_synthesizer_strips_out_of_range_markers():
    ledger = EvidenceLedger()
    ledger.add_search_hits(
        [SearchHit(chunk_id="D-1#chunk-0", document_id="D-1", score=0.9, text="text")]
    )
    llm = MockLLMClient(
        responses={
            "synthesize": (
                '{"answer": "Claim [1] and phantom [9].", "claims": ['
                '{"claim": "Claim", "evidence_ids": ["ev-0001"]}], '
                '"insufficient": false}'
            )
        }
    )
    draft = LLMSynthesizer(llm).synthesize(
        SynthesisRequest(question="q", question_type="semantic"), ledger
    )
    assert "[1]" in draft.answer
    assert "[9]" not in draft.answer


@pytest.mark.parametrize(
    "row,expected",
    [
        ({"site_id": "S-1", "month": "2024-01", "sum_patients_enrolled": 3}, "S-1"),
        ({"region_id": "R-2", "month": "2024-02", "total_patients_enrolled": 7}, "R-2"),
    ],
)
def test_row_keys_are_distinct_and_locatable(row, expected):
    ledger = EvidenceLedger()
    outcome = structured("site_metrics_monthly", [row])
    evidence = ledger.add_structured(outcome.result, "site_metrics_monthly")
    assert evidence and expected in evidence[0].location
