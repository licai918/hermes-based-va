"""Canonical Operational Policy Knowledge slot registry (ADR-0003).

The six Required Operational Policy Slots must exist as structured placeholders at
onboarding, before any business copy is written; an empty slot yields the governed
no-policy fallback, never improvised policy. Slot WORDING is business copy filled
via KnowledgeOps and is out of scope here (PRD \u00a7213), so every placeholder's content
stays empty and these tests lock that boundary. The registry keys are bound to the
eval publish-gate map (ADR-0075) so the two can't drift.
"""

from __future__ import annotations

from pathlib import Path

from eval_runner.fixtures import load_policy_slot_map
from toee_hermes.operational_policy import (
    POLICY_SLOT_ID_BY_KEY,
    REQUIRED_POLICY_SLOTS,
    SLOT_TITLES,
    authoring_slot_id_for,
    placeholder_slots,
    policy_slots_payload,
)

_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"

# The six slots in ADR-0003 order; keys mirror eval/policy_slot_map.yaml.
EXPECTED_SLOTS = (
    "business_hours_service_boundaries",
    "payment_payment_link_rules",
    "order_delivery_guidance",
    "accounting_inquiry_guidance",
    "returns_exchanges_stockout",
    "standard_exception_scripts",
)


def test_required_slots_are_the_six_adr_0003_slots_in_order() -> None:
    assert REQUIRED_POLICY_SLOTS == EXPECTED_SLOTS


def test_every_slot_has_a_human_title() -> None:
    assert set(SLOT_TITLES) == set(REQUIRED_POLICY_SLOTS)
    assert all(SLOT_TITLES[key].strip() for key in REQUIRED_POLICY_SLOTS)


def test_placeholder_slots_are_unfilled_with_no_business_copy() -> None:
    slots = placeholder_slots()
    assert [slot.key for slot in slots] == list(REQUIRED_POLICY_SLOTS)
    for slot in slots:
        assert slot.status == "empty"
        assert slot.content == ""  # WORDING is out of scope (PRD §213)
        assert slot.owner is None  # owner + review date are set at publish (ADR-0003)
        assert slot.review_date is None
        assert slot.title.strip()


def test_registry_keys_match_policy_slot_map() -> None:
    # The publish-gate map (ADR-0075) and the onboarding registry must name the same
    # slots, or a publish run could target a slot the registry does not model.
    slot_map = load_policy_slot_map(_EVAL_DIR)
    assert set(slot_map.slots) == set(REQUIRED_POLICY_SLOTS)


def test_payload_lists_six_empty_slots() -> None:
    payload = policy_slots_payload()
    assert [slot["key"] for slot in payload["slots"]] == list(REQUIRED_POLICY_SLOTS)
    assert all(
        slot["content"] == "" and slot["status"] == "empty"
        for slot in payload["slots"]
    )


# The kebab UI ids the authoring table (workbench_policy_slot, ADR-0145) and the
# in-memory KnowledgeStore key on, in ADR-0003 order — the other side of the
# ADR-0146 divergence #1 bridge.
EXPECTED_AUTHORING_IDS = (
    "business-hours",
    "payment-methods",
    "order-delivery",
    "accounting-inquiry",
    "returns-exchanges",
    "exception-scripts",
)


def test_policy_slot_id_bridge_is_total_and_bijective() -> None:
    # ADR-0146 divergence #1: the snake eval-gate keys and the kebab authoring ids
    # are bridged by one explicit map. It must cover every required slot and be 1:1,
    # or a promote could publish the wrong authoring row (or none).
    assert set(POLICY_SLOT_ID_BY_KEY) == set(REQUIRED_POLICY_SLOTS)
    kebab = [POLICY_SLOT_ID_BY_KEY[key] for key in REQUIRED_POLICY_SLOTS]
    assert kebab == list(EXPECTED_AUTHORING_IDS)
    assert len(set(kebab)) == len(kebab)  # bijective: no two keys share an id


def test_authoring_slot_id_for_resolves_known_and_refuses_unknown() -> None:
    assert authoring_slot_id_for("business_hours_service_boundaries") == "business-hours"
    assert authoring_slot_id_for("not_a_slot") is None
