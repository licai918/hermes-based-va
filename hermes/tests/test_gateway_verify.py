"""Textline webhook signature verification tests (ADR-0021).

Legacy simulate: HMAC-SHA256 of the exact raw body keyed by the shared secret.
Live TGP: SHA256({event_type}{event_time}{webhook_secret}) per Textline API docs.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from toee_hermes.gateway.verify import verify_textline_signature

SECRET = "whsec_textline_test"
CAPTURED_TGP_TIME = "1782847218"
CAPTURED_TGP_TYPE = "new_customer_post"
# ngrok capture of live Textline new_customer_post (2026-06-30, body "Hi buddy").
CAPTURED_TGP_SIGNATURE = (
    "e652f939697ccb429ccbd4ab6c5bbacf002b7e5c2bc899112a2b0d6b72aa0fa9"
)
_CAPTURED_BODY = Path(__file__).resolve().parents[2] / ".tmp" / "ngrok-body-bytes.bin"


def _sign_body(body: str, key: str = SECRET) -> str:
    return hmac.new(key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def _sign_tgp(*, event_type: str, event_time: str, secret: str = SECRET) -> str:
    return hashlib.sha256(f"{event_type}{event_time}{secret}".encode("utf-8")).hexdigest()


def test_accepts_signature_over_raw_body() -> None:
    raw = '{"event":"message:received","id":"evt_1"}'
    assert verify_textline_signature(raw_body=raw, signature=_sign_body(raw), secret=SECRET) is True


def test_rejects_wrong_secret() -> None:
    raw = "{}"
    assert (
        verify_textline_signature(raw_body=raw, signature=_sign_body(raw, "wrong"), secret=SECRET)
        is False
    )


def test_rejects_tampered_body() -> None:
    signature = _sign_body('{"amount":10}')
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


def test_accepts_tgp_type_time_secret_signature() -> None:
    event_time = "1782844993"
    signature = _sign_tgp(event_type="new_customer_post", event_time=event_time)
    raw = '{"webhook":"new_customer_post","post":{"body":"Hi"}}'
    assert (
        verify_textline_signature(
            raw_body=raw,
            signature=signature,
            secret=SECRET,
            event_time=event_time,
            event_type="new_customer_post",
        )
        is True
    )


def test_rejects_tgp_signature_with_wrong_event_type() -> None:
    event_time = "1782844993"
    signature = _sign_tgp(event_type="new_customer_post", event_time=event_time)
    assert (
        verify_textline_signature(
            raw_body='{"webhook":"new_customer_post"}',
            signature=signature,
            secret=SECRET,
            event_time=event_time,
            event_type="new_agent_post",
        )
        is False
    )


def test_accepts_captured_tgp_payload_with_resigned_secret() -> None:
    body = _CAPTURED_BODY.read_bytes()
    signature = _sign_tgp(
        event_type=CAPTURED_TGP_TYPE,
        event_time=CAPTURED_TGP_TIME,
    )
    assert (
        verify_textline_signature(
            raw_body=body,
            signature=signature,
            secret=SECRET,
            event_time=CAPTURED_TGP_TIME,
            event_type=CAPTURED_TGP_TYPE,
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
            event_type=CAPTURED_TGP_TYPE,
        )
        is False
    )


def test_accepts_sha256_prefix_on_signature() -> None:
    raw = '{"event":"message:received"}'
    signature = "sha256=" + _sign_body(raw)
    assert (
        verify_textline_signature(raw_body=raw, signature=signature, secret=SECRET)
        is True
    )
