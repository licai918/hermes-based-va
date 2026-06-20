"""Deterministic disclosure detector for the Launch Eval (ADR-0072, ADR-0118).

Disclosure assertions name policy-level expectations about an outbound reply. Most
of them (the fixed email support signature, the "no registered phone/email"
recovery scripts) are governed by Operational Policy Knowledge Slot 6 (ADR-0057)
and are enforced mechanically per-scenario via ``text.must_not_contain`` /
``text.must_contain`` — so they are intentionally NOT phrase-guessed here.

This module derives only the disclosures that are **content-free and structural**,
i.e. provable from the scenario's channel without knowing any policy wording.
"""

from __future__ import annotations


def derive_disclosures(*, channel: str) -> dict[str, bool]:
    """Derive the structural disclosure flags implied by a scenario's channel."""
    disclosures: dict[str, bool] = {}
    if channel == "email":
        # ADR-0056: the email channel never uses an SMS Session Opener.
        disclosures["no_sms_session_opener"] = True
    return disclosures
