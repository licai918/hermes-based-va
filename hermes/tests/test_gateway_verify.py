"""Textline webhook signature verification tests (ADR-0021).

Ports services/hermes-gateway verify-textline.test.ts: HMAC-SHA256 of the exact
raw body keyed by the shared secret, hex-encoded, compared in constant time.
"""

from __future__ import annotations

import hashlib
import hmac

from toee_hermes.gateway.verify import verify_textline_signature

SECRET = "whsec_textline_test"


def _sign(body: str, key: str = SECRET) -> str:
    return hmac.new(key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def test_accepts_signature_over_raw_body() -> None:
    raw = '{"event":"message:received","id":"evt_1"}'
    assert verify_textline_signature(raw_body=raw, signature=_sign(raw), secret=SECRET) is True


def test_rejects_wrong_secret() -> None:
    raw = "{}"
    assert (
        verify_textline_signature(raw_body=raw, signature=_sign(raw, "wrong"), secret=SECRET)
        is False
    )


def test_rejects_tampered_body() -> None:
    signature = _sign('{"amount":10}')
    assert (
        verify_textline_signature(
            raw_body='{"amount":1000}', signature=signature, secret=SECRET
        )
        is False
    )


def test_rejects_missing_or_empty_signature() -> None:
    assert verify_textline_signature(raw_body="{}", signature=None, secret=SECRET) is False
    assert verify_textline_signature(raw_body="{}", signature="", secret=SECRET) is False


def test_rejects_empty_secret() -> None:
    assert verify_textline_signature(raw_body="{}", signature="abc", secret="") is False


def test_length_mismatch_is_safe() -> None:
    assert verify_textline_signature(raw_body="{}", signature="deadbeef", secret=SECRET) is False
