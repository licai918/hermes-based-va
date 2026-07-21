"""SimpleTexting webhook authenticity check (ADR-0021).

SimpleTexting does not sign webhook payloads (no HMAC, no signature header). The
authenticity control is a shared secret token embedded in the webhook URL we
register (``/webhooks/simpletexting?token=<secret>``): only SimpleTexting and this
gateway know the URL. The route layer extracts the token; this function compares
it against the configured secret in constant time so the crypto core stays
provider-agnostic and unit-testable. Replay protection comes from messageId
idempotency in the pipeline, not from the token.
"""

from __future__ import annotations

import hmac
from typing import Optional


def verify_webhook_token(*, token: Optional[str], secret: str) -> bool:
    """Constant-time compare of the URL-supplied webhook token (fail-closed).

    Returns ``False`` when the token or the configured secret is missing/blank —
    an unconfigured gateway must never accept traffic.
    """
    if not token or not secret:
        return False
    return hmac.compare_digest(token.strip(), secret)
