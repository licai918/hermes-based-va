"""Deterministic disclosure detector for the Launch Eval (ADR-0072, ADR-0118).

Disclosure assertions name policy-level expectations about an outbound reply. This
module derives only the disclosures that are **content-free and structural**, i.e.
provable from the scenario's channel alone without reading the reply at all.

The reply-dependent ones live one layer up in :mod:`eval_runner.turn_result`:
``no_account_disclosure`` from the turn's governed tool calls, and the directory /
recovery-script invariants from the turn's governed outbound send. The fixed email
support signature's WORDING is the one that stays out of both — it is governed by
Operational Policy Knowledge Slot 6 (ADR-0057) and asserted per-scenario via
``text.must_contain`` when a scenario needs the literal string; what this module
derives is only the channel-structural fact that an email outbound carries one.
"""

from __future__ import annotations


def derive_disclosures(*, channel: str) -> dict[str, bool]:
    """Derive the structural disclosure flags implied by a scenario's channel."""
    disclosures: dict[str, bool] = {}
    if channel == "email":
        # ADR-0056: the email channel never uses an SMS Session Opener.
        disclosures["no_sms_session_opener"] = True
        # ADR-0056/Slot 6: every email outbound carries the fixed support signature
        # by construction. This is the content-free STRUCTURAL flag (the channel
        # requires a signature); the signature WORDING is still not phrase-guessed
        # here — it stays governed per-scenario via text.must_contain / the Tool Gate.
        disclosures["requires_email_support_signature"] = True
    return disclosures
