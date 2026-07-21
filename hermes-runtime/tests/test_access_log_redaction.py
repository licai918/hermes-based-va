"""The webhook token must never reach the access log (ADR-0021, ADR-0149).

SimpleTexting authenticates webhooks with a shared token in the registered URL —
its webhook API accepts only ``{url, triggers, requestPerSecLimit, accountPhone,
contactPhone}``, so there is no header or signature option to move the credential
to. The token therefore rides in the query string, and uvicorn's access logger
writes the full path-with-query verbatim. On Cloud Run that puts a live credential
into Cloud Logging, readable by every ``roles/logging.viewer`` principal — a far
wider audience than the Secret Manager grant it was deployed with.

Since the credential cannot leave the URL, the fix is at the log boundary.
"""

from __future__ import annotations

import logging

from hermes_runtime.access_log import (
    RedactQueryTokenFilter,
    install_access_log_redaction,
)

SECRET = "s3cret-webhook-token"


def _uvicorn_access_record(path_with_query: str) -> logging.LogRecord:
    """A record shaped exactly like uvicorn's access logger emits."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("10.0.0.1:0", "POST", path_with_query, "1.1", 200),
        exc_info=None,
    )


def test_filter_redacts_the_token_from_the_formatted_line() -> None:
    record = _uvicorn_access_record(f"/webhooks/simpletexting?token={SECRET}")

    assert RedactQueryTokenFilter().filter(record) is True
    rendered = record.getMessage()

    assert SECRET not in rendered
    assert "token=[REDACTED]" in rendered
    assert "/webhooks/simpletexting" in rendered  # route still greppable
    assert '"POST' in rendered and "200" in rendered  # method/status intact


def test_filter_leaves_untokened_paths_alone() -> None:
    record = _uvicorn_access_record("/healthz")

    RedactQueryTokenFilter().filter(record)

    assert "/healthz" in record.getMessage()


def test_filter_redacts_only_the_token_among_several_params() -> None:
    record = _uvicorn_access_record(f"/webhooks/simpletexting?a=1&token={SECRET}&b=2")

    RedactQueryTokenFilter().filter(record)
    rendered = record.getMessage()

    assert SECRET not in rendered
    assert "a=1" in rendered and "b=2" in rendered


def test_install_is_idempotent_and_attaches_to_the_uvicorn_access_logger() -> None:
    logger = logging.getLogger("uvicorn.access")
    before = len(logger.filters)

    install_access_log_redaction()
    install_access_log_redaction()

    added = [f for f in logger.filters if isinstance(f, RedactQueryTokenFilter)]
    assert len(added) == 1
    assert len(logger.filters) == before + 1
