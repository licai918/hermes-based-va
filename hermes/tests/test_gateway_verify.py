"""Textline webhook signature verification tests (ADR-0021).

Ports services/hermes-gateway verify-textline.test.ts: HMAC-SHA256 of the exact
raw body keyed by the shared secret, hex-encoded, compared in constant time.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from toee_hermes.gateway.verify import verify_textline_signature

SECRET = "whsec_textline_test"
CAPTURED_TGP_TIME = "1782844993"
# ngrok capture of a live Textline new_customer_post (2026-06-30); signature was
# not produced with our test secret — documents real-provider mismatch separately.
CAPTURED_TGP_SIGNATURE = (
    "0f89806093f094ce8f54999cd9100806c21a8735e2c244382c6bb3c20fee639d"
)
_CAPTURED_BODY = Path(__file__).resolve().parents[2] / ".tmp" / "ngrok-body-bytes.bin"


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


def test_accepts_tgp_timestamped_signature() -> None:
    raw = '{"webhook":"new_customer_post","post":{"body":"Hi"}}'
    event_time = "1782844993"
    signed = f"{event_time}.{raw}"
    signature = _sign(signed)
    assert (
        verify_textline_signature(
            raw_body=raw,
            signature=signature,
            secret=SECRET,
            event_time=event_time,
        )
        is True
    )


def test_rejects_tgp_signature_with_wrong_timestamp() -> None:
    raw = '{"webhook":"new_customer_post"}'
    signature = _sign(f"1782844993.{raw}")
    assert (
        verify_textline_signature(
            raw_body=raw,
            signature=signature,
            secret=SECRET,
            event_time="9999999999",
        )
        is False
    )


def test_accepts_captured_tgp_payload_resigned_with_secret() -> None:
    body = _CAPTURED_BODY.read_bytes()
    signed = f"{CAPTURED_TGP_TIME}.".encode("utf-8") + body
    signature = hmac.new(SECRET.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    assert (
        verify_textline_signature(
            raw_body=body,
            signature=signature,
            secret=SECRET,
            event_time=CAPTURED_TGP_TIME,
        )
        is True
    )


def test_rejects_captured_textline_signature_with_unrelated_secret() -> None:
    body = _CAPTURED_BODY.read_bytes()
    assert (
        verify_textline_signature(
            raw_body=body,
            signature=CAPTURED_TGP_SIGNATURE,
            secret=SECRET,
            event_time=CAPTURED_TGP_TIME,
        )
        is False
    )


def test_accepts_sha256_prefix_on_signature() -> None:
    raw = '{"event":"message:received"}'
    signature = "sha256=" + _sign(raw)
    assert (
        verify_textline_signature(raw_body=raw, signature=signature, secret=SECRET)
        is True
    )
