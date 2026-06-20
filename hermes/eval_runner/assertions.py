"""Launch Eval standard assertion package (ports assertions.ts, ADR-0072, ADR-0118).

Each scenario carries behavioral / tool / disclosure / text / memory assertions.
:func:`evaluate_scenario` checks every present block against an agent turn result
and returns one :class:`AssertionOutcome` per assertion. A failed outcome fails
the scenario at its ``max_severity`` (the report layer applies severity).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .harness import AgentTurnResult
from .types import MergedScenario


@dataclass(frozen=True)
class AssertionOutcome:
    """One checked assertion; ``passed is False`` contributes to a scenario failure."""

    type: str  # "behavioral" | "tool" | "disclosure" | "text" | "memory"
    name: str
    passed: bool
    detail: str


def _json(value: Any) -> str:
    try:
        return json.dumps(value)
    except TypeError:
        return repr(value)


def _call_matches(tool: str, action: str, expected: Mapping[str, Any]) -> bool:
    if tool != expected.get("tool"):
        return False
    expected_action = expected.get("action")
    return expected_action is None or action == expected_action


def _describe_call(expected: Mapping[str, Any]) -> str:
    action = expected.get("action")
    return f"{expected.get('tool')}.{action}" if action else str(expected.get("tool"))


def _eval_behavioral(
    behavioral: Mapping[str, Any], result: AgentTurnResult
) -> list[AssertionOutcome]:
    outcomes: list[AssertionOutcome] = []
    for name, expected in behavioral.items():
        if name == "case_created":
            actual: Any = result.case_created
        elif name == "case_urgency":
            actual = result.case_urgency
        elif name == "contact_reason":
            actual = result.contact_reason
        elif name == "alternate_address_not_verified":
            actual = (
                result.alternate_address_not_verified
                if result.alternate_address_not_verified is not None
                else False
            )
        else:
            actual = None
        outcomes.append(
            AssertionOutcome(
                type="behavioral",
                name=name,
                passed=actual == expected,
                detail=f"expected {name}={_json(expected)}, got {_json(actual)}",
            )
        )
    return outcomes


def _eval_tool(
    tool: Mapping[str, Any], result: AgentTurnResult
) -> list[AssertionOutcome]:
    outcomes: list[AssertionOutcome] = []
    for expected in tool.get("expect_calls") or []:
        found = any(
            _call_matches(call.tool, call.action, expected)
            for call in result.tool_calls
        )
        outcomes.append(
            AssertionOutcome(
                type="tool",
                name=f"expect_call {_describe_call(expected)}",
                passed=found,
                detail="called" if found else "expected tool call was not made",
            )
        )
    for forbidden in tool.get("forbidden_tools") or []:
        called = any(
            _call_matches(call.tool, call.action, forbidden)
            for call in result.tool_calls
        )
        outcomes.append(
            AssertionOutcome(
                type="tool",
                name=f"forbidden {_describe_call(forbidden)}",
                passed=not called,
                detail="forbidden tool call was made" if called else "not called",
            )
        )
    return outcomes


def _eval_disclosure(
    disclosure: Mapping[str, bool], result: AgentTurnResult
) -> list[AssertionOutcome]:
    outcomes: list[AssertionOutcome] = []
    for name, expected in disclosure.items():
        actual = result.disclosures.get(name)
        outcomes.append(
            AssertionOutcome(
                type="disclosure",
                name=name,
                passed=actual == expected,
                detail=f"expected {name}={expected}, got {_json(actual)}",
            )
        )
    return outcomes


def _eval_text(
    text: Mapping[str, Any], result: AgentTurnResult
) -> list[AssertionOutcome]:
    haystack = result.outbound_text.lower()
    outcomes: list[AssertionOutcome] = []
    for phrase in text.get("must_contain") or []:
        passed = phrase.lower() in haystack
        outcomes.append(
            AssertionOutcome(
                type="text",
                name=f'must_contain "{phrase}"',
                passed=passed,
                detail="present" if passed else "missing from outbound text",
            )
        )
    for phrase in text.get("must_not_contain") or []:
        passed = phrase.lower() not in haystack
        outcomes.append(
            AssertionOutcome(
                type="text",
                name=f'must_not_contain "{phrase}"',
                passed=passed,
                detail="absent" if passed else "present in outbound text",
            )
        )
    return outcomes


def _eval_memory(
    memory: Mapping[str, Any], result: AgentTurnResult
) -> list[AssertionOutcome]:
    outcomes: list[AssertionOutcome] = []
    did_upsert = len(result.memory_upserts) > 0 or any(
        call.tool == "toee_customer_memory" and call.action == "upsert_preference"
        for call in result.tool_calls
    )

    if memory.get("expect_upsert") is True:
        outcomes.append(
            AssertionOutcome(
                type="memory",
                name="expect_upsert",
                passed=did_upsert,
                detail="upsert occurred"
                if did_upsert
                else "no preference upsert observed",
            )
        )
    if memory.get("expect_upsert_slot") is not None:
        slot = memory["expect_upsert_slot"]
        passed = slot in result.memory_upserts
        outcomes.append(
            AssertionOutcome(
                type="memory",
                name=f"expect_upsert_slot {slot}",
                passed=passed,
                detail="slot upserted" if passed else f"slot {slot} was not upserted",
            )
        )
    if memory.get("forbid_inferred_upsert") is True:
        outcomes.append(
            AssertionOutcome(
                type="memory",
                name="forbid_inferred_upsert",
                passed=not did_upsert,
                detail="an inferred upsert was made"
                if did_upsert
                else "no inferred upsert",
            )
        )
    if memory.get("honor_injected_preference") is True:
        passed = result.honored_injected_preference is True
        outcomes.append(
            AssertionOutcome(
                type="memory",
                name="honor_injected_preference",
                passed=passed,
                detail="injected preference honored"
                if passed
                else "injected preference not honored (or re-asked)",
            )
        )
    return outcomes


def evaluate_scenario(
    scenario: MergedScenario, result: AgentTurnResult
) -> list[AssertionOutcome]:
    """Run the standard assertion package for one scenario against a turn result."""
    a = scenario.assertions
    outcomes: list[AssertionOutcome] = []
    if a.behavioral:
        outcomes.extend(_eval_behavioral(a.behavioral, result))
    if a.tool:
        outcomes.extend(_eval_tool(a.tool, result))
    if a.disclosure:
        outcomes.extend(_eval_disclosure(a.disclosure, result))
    if a.text:
        outcomes.extend(_eval_text(a.text, result))
    if a.memory_assertions:
        outcomes.extend(_eval_memory(a.memory_assertions, result))
    return outcomes
