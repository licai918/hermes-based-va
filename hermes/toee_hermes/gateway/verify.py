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
from typing import Optional


def verify_textline_signature(
    *, raw_body: str, signature: Optional[str], secret: str
) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    # compare_digest is constant time and length-safe, so an unequal-length
    # signature can neither leak timing nor raise.
    return hmac.compare_digest(expected, signature)
