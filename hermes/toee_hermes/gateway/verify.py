"""Textline webhook authenticity check (ADR-0021).

v1 uses an HMAC-SHA256 of the exact raw request body keyed by the shared webhook
secret, hex-encoded, and compared in constant time against the provider
signature header. The header name and any version prefix are extracted by the
route layer; this function operates purely on the already-extracted signature
string so the crypto core stays provider-agnostic and unit-testable.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional, Union

RawBody = Union[str, bytes]


def _normalize_signature(signature: Optional[str]) -> Optional[str]:
    if not signature:
        return None
    sig = signature.strip()
    for prefix in ("sha256=", "v1=", "v1,"):
        if sig.startswith(prefix):
            sig = sig[len(prefix) :]
            break
    return sig.lower()


def _body_bytes(raw_body: RawBody) -> bytes:
    if isinstance(raw_body, bytes):
        return raw_body
    return raw_body.encode("utf-8")


def verify_textline_signature(
    *,
    raw_body: RawBody,
    signature: Optional[str],
    secret: str,
    event_time: Optional[str] = None,
    event_type: Optional[str] = None,
) -> bool:
    """Verify Textline webhook signatures (hex).

    Live Textline (TGP) sends ``X-Tgp-Event-Signature``, ``X-Tgp-Event-Time``, and
    ``X-Tgp-Event-Type``. Per Textline API docs, the signature is
    ``SHA256({event_type}{event_time}{webhook_secret})`` — not HMAC and not over
    the body. Legacy local simulate uses ``X-Textline-Signature`` =
    HMAC-SHA256(raw body, secret).
    """
    sig = _normalize_signature(signature)
    if not sig or not secret:
        return False

    if event_type and event_time:
        expected = hashlib.sha256(
            f"{event_type.strip()}{event_time.strip()}{secret}".encode("utf-8")
        ).hexdigest()
        return hmac.compare_digest(expected, sig)

    body = _body_bytes(raw_body)
    key = secret.encode("utf-8")
    expected = hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
