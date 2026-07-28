"""Tests for the deterministic disclosure detector (``eval_runner.disclosures``).

Only content-free, ADR-grounded disclosures are derived here. ADR-0056 fixes that
the email channel never carries an SMS Session Opener (ADR-0024), so
``no_sms_session_opener`` is true by construction on the email channel. Everything
that depends on what the turn actually sent — including the recovery-script
invariants — lives in :mod:`eval_runner.turn_result` (see
``test_eval_turn_result.py``); the fixed signature's WORDING stays governed by
Operational Policy Knowledge Slot 6 (ADR-0057) and is not phrase-guessed anywhere.
"""

from __future__ import annotations

from eval_runner.disclosures import derive_disclosures


def test_email_channel_satisfies_no_sms_session_opener() -> None:
    # ADR-0056: every email outbound omits the SMS Session Opener by construction
    # and carries the fixed support signature (the structural flag, not its wording).
    assert derive_disclosures(channel="email") == {
        "no_sms_session_opener": True,
        "requires_email_support_signature": True,
    }


def test_sms_channel_does_not_assert_no_sms_session_opener() -> None:
    # ADR-0024: a new SMS Session REQUIRES an opener, so its absence is never a
    # disclosure the SMS channel can satisfy structurally.
    assert "no_sms_session_opener" not in derive_disclosures(channel="simpletexting")
