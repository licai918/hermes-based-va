"""SimpleTexting webhook token verification tests (ADR-0021 requirement, ADR-0153 mechanism).

SimpleTexting does not sign webhook payloads: authenticity is a shared secret
token in the registered webhook URL, compared in constant time (fail-closed).
"""

from __future__ import annotations

from toee_hermes.gateway.verify import verify_webhook_token

SECRET = "whtok_simpletexting_test"


def test_accepts_the_registered_token() -> None:
    assert verify_webhook_token(token=SECRET, secret=SECRET) is True


def test_accepts_a_token_with_surrounding_whitespace() -> None:
    assert verify_webhook_token(token=f"  {SECRET} ", secret=SECRET) is True


def test_rejects_a_wrong_token() -> None:
    assert verify_webhook_token(token="wrong", secret=SECRET) is False


def test_rejects_missing_or_empty_token() -> None:
    assert verify_webhook_token(token=None, secret=SECRET) is False
    assert verify_webhook_token(token="", secret=SECRET) is False


def test_rejects_empty_secret_even_with_matching_token() -> None:
    # An unconfigured gateway must never accept traffic (fail-closed).
    assert verify_webhook_token(token="", secret="") is False
    assert verify_webhook_token(token="anything", secret="") is False


def test_rejects_a_token_that_is_a_prefix_of_the_secret() -> None:
    assert verify_webhook_token(token=SECRET[:-1], secret=SECRET) is False


def test_rejects_a_non_ascii_token_without_raising() -> None:
    # hmac.compare_digest raises TypeError on non-ASCII str operands, which turned
    # an unauthenticated request into a 500 (and, since the provider retries 5xx,
    # a retry storm). A forged token must be a plain False.
    assert verify_webhook_token(token="café", secret=SECRET) is False
    assert verify_webhook_token(token="日本語", secret=SECRET) is False
