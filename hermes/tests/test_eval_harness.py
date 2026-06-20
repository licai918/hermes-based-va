"""Tests for the Launch Eval agent harness (ports harness.test.ts, ADR-0071).

The harness composes a scenario's merged mock context into a driver, forces
error-marked domains into governed failures, and builds the External profile
execution context + Tool Gate the eval runs every scenario under. The agent
harness itself is a deterministic stub until the live External Customer Service
turn is wired in (later slice), so scenarios fail closed and the gate is provable.
"""

from __future__ import annotations

from pathlib import Path

from eval_runner.fixtures import load_scenario
from eval_runner.harness import (
    AgentTurnResult,
    create_scenario_driver,
    scenario_execution_context,
    scenario_tool_gate,
    stub_agent_harness,
)
from toee_hermes.execute import execute_tool

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def test_verified_customer_reads_invoice_when_email_link_linked_01() -> None:
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    result = execute_tool(
        tool="toee_qbo_read",
        action="get_invoice",
        params={"invoice_number": "INV-9001"},
        context=scenario_execution_context(scenario),
        driver=create_scenario_driver(scenario.mock_context),
        gate=scenario_tool_gate(scenario),
    )
    assert result.ok is True


def test_blocks_invoice_read_when_email_link_override_fails_04() -> None:
    scenario = load_scenario("text_first_launch", "04", EVAL_DIR)
    result = execute_tool(
        tool="toee_qbo_read",
        action="get_invoice",
        params={"invoice_number": "INV-9001"},
        context=scenario_execution_context(scenario),
        driver=create_scenario_driver(scenario.mock_context),
        gate=scenario_tool_gate(scenario),
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_forces_governed_failure_for_error_marked_domain_13_shopify() -> None:
    scenario = load_scenario("text_first_launch", "13", EVAL_DIR)
    result = execute_tool(
        tool="toee_shopify_read",
        action="search_products",
        params={"query": "tire"},
        context=scenario_execution_context(scenario),
        driver=create_scenario_driver(scenario.mock_context),
        gate=scenario_tool_gate(scenario),
    )
    assert result.ok is False
    assert result.error_class == "vendor_timeout"


def test_error_marked_domain_does_not_break_other_domains_13() -> None:
    # Only the error-marked domain (shopify) fails; knowledge stays available.
    scenario = load_scenario("text_first_launch", "13", EVAL_DIR)
    result = execute_tool(
        tool="toee_knowledge_search",
        action="search_public_site",
        params={"query": "tire"},
        context=scenario_execution_context(scenario),
        driver=create_scenario_driver(scenario.mock_context),
        gate=scenario_tool_gate(scenario),
    )
    assert result.ok is True


def test_stub_agent_harness_returns_deterministic_empty_turn() -> None:
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    result = stub_agent_harness.run_turn(scenario)
    assert result == AgentTurnResult(
        outbound_text="",
        tool_calls=[],
        case_created=False,
        disclosures={},
        memory_upserts=[],
    )
