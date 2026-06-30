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
) -> bool:
    """Verify Textline webhook HMAC-SHA256 (hex).

    Live Textline (TGP) sends ``X-Tgp-Event-Signature`` + ``X-Tgp-Event-Time`` and
    signs ``{event_time}.{raw_body}`` over the exact request bytes. Legacy local
    simulate uses ``X-Textline-Signature`` over the raw body only.
    """
    sig = _normalize_signature(signature)
    if not sig or not secret:
        return False
    body = _body_bytes(raw_body)
    key = secret.encode("utf-8")
    messages: list[bytes] = [body]
    if event_time:
        ts = event_time.strip().encode("utf-8")
        # TGP live webhooks (Stripe-style timestamped payload).
        messages = [ts + b"." + body, ts + b":" + body, body]
    for message in messages:
        expected = hmac.new(key, message, hashlib.sha256).hexdigest()
        # compare_digest is constant time and length-safe, so an unequal-length
        # signature can neither leak timing nor raise.
        if hmac.compare_digest(expected, sig):
            return True
    return False
