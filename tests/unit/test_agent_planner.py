"""Planner / router unit tests: question type -> tool intents."""

from __future__ import annotations

import pytest

from nexusgraph.agent.planner import HeuristicRouter, LLMPlanner
from nexusgraph.domain.models import Entity
from nexusgraph.llm.mock import MockLLMClient

ROUTER = HeuristicRouter()

SITE_A = Entity(id="site:S-1001", type="site", name="Site A")
REGION = Entity(id="region:R-02", type="region", name="Western Europe Cluster")


def intents(plan) -> list[str]:
    return [s.args.get("intent", "") for s in plan.steps]


def test_semantic_question_routes_to_retrieval():
    plan = ROUTER.plan("What do monitoring reports say about data quality?", [])
    assert plan.question_type == "semantic"
    assert intents(plan) == ["search"]


def test_quantitative_site_question_uses_structured_tool():
    plan = ROUTER.plan("How did patient enrolment change at Site A over time?",
                       [SITE_A])
    assert plan.question_type == "quantitative"
    assert "site_trends" in intents(plan)
    # the resolved site is passed as a filter to at least one step
    site_ids = [s.args.get("site_id") for s in plan.steps]
    assert "S-1001" in site_ids


def test_regional_question_produces_both_region_marts():
    plan = ROUTER.plan(
        "Which region has increasing enrolment and what is happening to "
        "investigator capacity in that region?", [REGION])
    assert plan.question_type in ("quantitative", "mixed")
    assert "region_enrolment" in intents(plan)
    assert "region_capacity" in intents(plan)
    assert plan.steps[0].args.get("region_id") == "R-02"


def test_multi_hop_delayed_products_is_relationship():
    plan = ROUTER.plan("Which products are derived from trials that have "
                       "delayed milestones?", [])
    assert plan.question_type == "relationship"
    assert intents(plan) == ["products_of_delayed_trials"]


def test_mixed_question_combines_graph_and_sql():
    plan = ROUTER.plan(
        "Why is enrolment falling at Site A and which compounds named in "
        "safety reports are associated with that site?", [SITE_A])
    assert plan.question_type == "mixed"
    found = intents(plan)
    assert "compounds_with_safety_sites" in found
    assert "site_trends" in found


def test_entity_lookup_question():
    plan = ROUTER.plan("Tell me about Site A.", [SITE_A])
    assert plan.question_type == "entity_lookup"
    assert plan.steps[0].tool == "get_entity"
    assert plan.steps[0].args["entity_id"] == "site:S-1001"


def test_unanswerable_question_has_no_steps():
    plan = ROUTER.plan("What is the market share of NexuPharm?", [])
    assert plan.question_type == "unanswerable"
    assert plan.steps == []


def test_llm_planner_falls_back_on_garbage_output():
    llm = MockLLMClient(responses={"plan": "not json at all"})
    planner = LLMPlanner(llm)
    plan = planner.plan("Which trials have delayed milestones?", [])
    assert plan.question_type == "relationship"
    assert llm.calls and llm.calls[0].task == "plan"


def test_llm_planner_rejects_unknown_tools():
    llm = MockLLMClient(responses={"plan": (
        '{"question_type": "mixed", "steps": [{"tool": "drop_tables"}], '
        '"rationale": "x"}')})
    planner = LLMPlanner(llm)
    plan = planner.plan("Any question at all", [])
    # unknown tool -> validation error -> heuristic fallback
    assert all(step.tool != "drop_tables" for step in plan.steps)


@pytest.mark.parametrize("question,expected_type", [
    ("What is patient enrolment at Site A?", "quantitative"),
    ("Which documents mention Site A?", "relationship"),
])
def test_type_matrix(question, expected_type):
    resolved = [SITE_A] if "Site A" in question else []
    plan = ROUTER.plan(question, resolved)
    assert plan.question_type == expected_type
