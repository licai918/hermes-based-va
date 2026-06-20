"""Canonical Operational Policy Knowledge slot registry (ADR-0003).

The **External Customer Service Profile** answers policy-bound questions only from
published **Operational Policy Knowledge**. ADR-0003 requires six **Required
Operational Policy Slots** to exist as *structured placeholders* at onboarding —
before any copy is written — so an empty slot produces the governed no-policy
fallback (and a Follow-up Case where appropriate) instead of improvised policy.

This module is the single source of truth for the slot set: the slot keys, their
human titles (from ADR-0003), and the empty-placeholder shape supervisors fill via
``toee_knowledge_ops`` (KnowledgeOps). Each slot gains an owner and review date at
publish time. Slot WORDING is business copy filled through KnowledgeOps and is out
of scope for this codebase (PRD §213), so placeholders carry empty ``content``.

Keys mirror ``eval/policy_slot_map.yaml`` (the publish-gate map, ADR-0075); a test
binds the two so they cannot drift.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Slot status lifecycle: an onboarding placeholder is "empty" until published.
SLOT_STATUS_EMPTY = "empty"

# The six Required Operational Policy Slots in ADR-0003 order. Keys are the stable
# identifiers shared with eval/policy_slot_map.yaml and the knowledge tools.
REQUIRED_POLICY_SLOTS: tuple[str, ...] = (
    "business_hours_service_boundaries",
    "payment_payment_link_rules",
    "order_delivery_guidance",
    "accounting_inquiry_guidance",
    "returns_exchanges_stockout",
    "standard_exception_scripts",
)

# Human-readable slot titles, verbatim from ADR-0003. These name the policy *area*;
# the policy text itself is KnowledgeOps-published business copy (PRD §213).
SLOT_TITLES: dict[str, str] = {
    "business_hours_service_boundaries": (
        "Business hours and service boundaries (including after-hours limits)"
    ),
    "payment_payment_link_rules": "Payment methods and Payment Link rules",
    "order_delivery_guidance": "Order and delivery inquiry guidance",
    "accounting_inquiry_guidance": (
        "Accounting inquiry guidance (including email-link failure handling)"
    ),
    "returns_exchanges_stockout": (
        "Returns, exchanges, and stockout policy (operational interpretation layer)"
    ),
    "standard_exception_scripts": (
        "Standard exception scripts (unmatched caller, ambiguous match, email link "
        "failure, urgent cases, standard non-customer inbound intake, and email "
        "support signature text)"
    ),
}


@dataclass(frozen=True)
class PolicySlot:
    """One Required Operational Policy Slot.

    ``owner`` and ``review_date`` are assigned at publish time via KnowledgeOps
    (ADR-0003); ``content`` is the published business copy and stays empty until
    then (PRD §213). ``status`` is ``"empty"`` for an unfilled onboarding placeholder.
    """

    key: str
    title: str
    status: str = SLOT_STATUS_EMPTY
    owner: str | None = None
    review_date: str | None = None
    content: str = ""


def placeholder_slots() -> list[PolicySlot]:
    """Return the six required slots as empty onboarding placeholders (ADR-0003)."""
    return [PolicySlot(key=key, title=SLOT_TITLES[key]) for key in REQUIRED_POLICY_SLOTS]


def policy_slots_payload() -> dict[str, Any]:
    """Return ``{"slots": [...]}`` for ``toee_knowledge_ops.get_policy_slots``.

    A pure function of the registry (no clock/randomness), so governed reads and
    eval runs see a stable, ordered shape.
    """
    return {"slots": [asdict(slot) for slot in placeholder_slots()]}
