"""SMS opt-out keyword detection tests (ADR-0108, ADR-0015, ADR-0016).

Ports services/hermes-gateway opt-out.test.ts: whole-word, case-insensitive
detection so an embedded keyword (e.g. "nonstop") does not opt a customer out.
"""

from __future__ import annotations

from toee_hermes.gateway.opt_out import SMS_OPT_OUT_CONFIRMATION, is_opt_out_keyword


def test_detects_stop_case_insensitive() -> None:
    assert is_opt_out_keyword("STOP") is True
    assert is_opt_out_keyword("stop") is True
    assert is_opt_out_keyword("Please STOP") is True


def test_detects_unsubscribe_and_arret() -> None:
    assert is_opt_out_keyword("unsubscribe") is True
    assert is_opt_out_keyword("ARRET") is True


def test_whole_word_only() -> None:
    assert is_opt_out_keyword("nonstop") is False
    assert is_opt_out_keyword("stopwatch") is False


def test_empty_body_is_false() -> None:
    assert is_opt_out_keyword("") is False


def test_confirmation_is_fixed_and_brief() -> None:
    assert "unsubscribed" in SMS_OPT_OUT_CONFIRMATION.lower()
    assert "?" not in SMS_OPT_OUT_CONFIRMATION
