import pytest
from pydantic import ValidationError

from nexusgraph.domain.models import (
    Aggregation,
    Claim,
    Evidence,
    FilterCondition,
    QuerySpec,
    SourceType,
    Usage,
)


def test_evidence_is_immutable() -> None:
    ev = Evidence(
        evidence_id="ev-0001", source_id="doc:D-1", source_type=SourceType.document,
        location="doc:D-1#chunk-0001",
    )
    with pytest.raises(ValidationError):
        ev.source_id = "doc:D-2"  # type: ignore[misc]


def test_query_spec_limit_bounds() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(table="trials", limit=10_000)
    QuerySpec(
        table="trial_enrolment",
        filters=[FilterCondition(column="site_id", op="eq", value="S-1001")],
        aggregations=[Aggregation(func="sum", column="patients_enrolled")],
    )


def test_claim_requires_text() -> None:
    with pytest.raises(ValidationError):
        Claim(claim="")
    Claim(claim="Site S-1001 enrolment declined.", evidence_ids=["ev-0001"])


def test_usage_accumulates() -> None:
    a = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15, llm_calls=1,
              estimated_cost_usd=0.001)
    b = Usage(prompt_tokens=7, completion_tokens=3, total_tokens=10, llm_calls=1,
              estimated_cost_usd=0.002)
    a.add(b)
    assert a.total_tokens == 25
    assert a.llm_calls == 2
    assert abs(a.estimated_cost_usd - 0.003) < 1e-9
