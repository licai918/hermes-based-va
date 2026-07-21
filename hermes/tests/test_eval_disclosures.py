"""Tests for the deterministic disclosure detector (``eval_runner.disclosures``).

Only content-free, ADR-grounded disclosures are derived here. ADR-0056 fixes that
the email channel never carries an SMS Session Opener (ADR-0024), so
``no_sms_session_opener`` is true by construction on the email channel. The
policy-slot-governed disclosure wording (the fixed signature, recovery scripts)
lives in Operational Policy Knowledge Slot 6 (ADR-0057) and is intentionally NOT
phrase-guessed here.
"""

from __future__ import annotations

from eval_runner.disclosures import derive_disclosures


def test_email_channel_satisfies_no_sms_session_opener() -> None:
    # ADR-0056: every email outbound omits the SMS Session Opener by construction.
    assert derive_disclosures(channel="email") == {"no_sms_session_opener": True}


def test_sms_channel_does_not_assert_no_sms_session_opener() -> None:
    # ADR-0024: a new SMS Session REQUIRES an opener, so its absence is never a
    # disclosure the SMS channel can satisfy structurally.
    assert "no_sms_session_opener" not in derive_disclosures(channel="simpletexting")
