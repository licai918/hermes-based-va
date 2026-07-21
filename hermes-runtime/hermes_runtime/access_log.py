"""Keep the webhook token out of the access log (ADR-0021, ADR-0153).

SimpleTexting's webhook registration accepts only ``{url, triggers,
requestPerSecLimit, accountPhone, contactPhone}`` — no header, no secret, no
signature field — so the shared token has to live in the URL we register. Uvicorn's
access logger writes the full path *with* query string, which on Cloud Run puts a
live credential into Cloud Logging where any ``roles/logging.viewer`` principal can
read it; that is a much wider audience than the Secret Manager grant the value was
deployed under.

The credential cannot move, so it is masked at the log boundary instead. The route
is left intact so access logs stay useful for debugging.

**This covers the application log only.** Cloud Run emits its own request log with
``httpRequest.requestUrl`` — query string included — and so does any fronting load
balancer or proxy; none of that passes through this logger. Treat the registered
webhook URL as a live credential wherever request logs are readable, and rotate the
token (re-register the webhook) if that audience is ever wider than intended.
"""

from __future__ import annotations

import logging
import re

# Matches the token value in a query string, leaving other params untouched.
_TOKEN_PARAM = re.compile(r"(?i)(\btoken=)[^&\s]*")

_REDACTED = r"\1[REDACTED]"

# uvicorn.access formats with args = (client_addr, method, full_path, http_version,
# status_code); the path is the one field that can carry the query string.
_PATH_ARG_INDEX = 2


class RedactQueryTokenFilter(logging.Filter):
    """Mask ``token=...`` in uvicorn access records before they are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > _PATH_ARG_INDEX:
            path = args[_PATH_ARG_INDEX]
            if isinstance(path, str) and "token=" in path.lower():
                masked = _TOKEN_PARAM.sub(_REDACTED, path)
                record.args = (
                    args[:_PATH_ARG_INDEX] + (masked,) + args[_PATH_ARG_INDEX + 1 :]
                )
        # Defensive: a differently-shaped record still gets its message scrubbed.
        elif isinstance(record.msg, str) and "token=" in record.msg.lower():
            record.msg = _TOKEN_PARAM.sub(_REDACTED, record.msg)
        return True


def install_access_log_redaction() -> None:
    """Attach the redaction filter to the uvicorn access logger (idempotent)."""
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(f, RedactQueryTokenFilter) for f in logger.filters):
        return
    logger.addFilter(RedactQueryTokenFilter())
