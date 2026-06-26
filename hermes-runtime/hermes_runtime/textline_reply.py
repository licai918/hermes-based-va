"""Real Textline outbound ReplySender (ADR-0066/0083/0104, ADR-0020).

The gateway delivers one customer-facing reply per turn through a ``ReplySender``
``(conversation_id, body)``. In production that send is the Textline REST API:

    POST {base_url}/api/conversations.json
    X-TGP-ACCESS-TOKEN: <Textline Developer API access token>
    {"uuid": "<conversation uuid>", "comment": {"body": "<message text>"}}

The base URL (``https://application.textline.com/``), the ``X-TGP-ACCESS-TOKEN``
auth header, and the ``api/conversations.json`` endpoint are confirmed by the dltHub
Textline API source and Ibexa Connect's "Message a Conversation" action. The exact
request-body field names are the one detail to confirm against a live Textline
account before go-live; they are isolated in :func:`_build_payload` for that reason.

The HTTP transport is injected (default: stdlib ``urllib.request``, no new runtime
dependency) so the sender is unit-testable without the network. A non-2xx response
raises :class:`TextlineSendError`: a failed delivery must surface to the caller,
never be silently dropped (ADR-0104 error handling) or reported as a success
(ADR-0020 no fabrication).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

# Textline Developer API access token header (dltHub Textline source).
TEXTLINE_ACCESS_TOKEN_HEADER = "X-TGP-ACCESS-TOKEN"

# Textline hosted REST API; overridable for a proxy via env.
TEXTLINE_DEFAULT_BASE_URL = "https://application.textline.com/"

_CONVERSATIONS_PATH = "api/conversations.json"

_ACCESS_TOKEN_ENV = "TEXTLINE_ACCESS_TOKEN"
_BASE_URL_ENV = "TEXTLINE_API_BASE_URL"

# (url, headers, body) -> HTTP status code. Injected in tests; the default below
# performs the real POST.
Transport = Callable[..., int]


class TextlineSendError(RuntimeError):
    """A Textline outbound send failed (non-2xx response or transport error)."""


@dataclass(frozen=True)
class TextlineConfig:
    """Resolved Textline connection for outbound sends."""

    base_url: str
    access_token: str


def resolve_textline_config() -> TextlineConfig:
    """Resolve the Textline connection from the environment (fail-closed).

    Raises ``ValueError`` when ``TEXTLINE_ACCESS_TOKEN`` is missing or blank: a
    missing token is a deploy misconfiguration, never a silent unauthed send.
    """
    access_token = (os.environ.get(_ACCESS_TOKEN_ENV) or "").strip()
    if not access_token:
        raise ValueError(
            f"{_ACCESS_TOKEN_ENV} is required to send Textline replies "
            "(ADR-0083); set it in the environment."
        )
    base_url = (os.environ.get(_BASE_URL_ENV) or "").strip() or TEXTLINE_DEFAULT_BASE_URL
    return TextlineConfig(base_url=base_url, access_token=access_token)


def _build_payload(conversation_id: str, body: str) -> bytes:
    """Serialize the "message a conversation" request body.

    Field names per the Textline Developer API "message a conversation" action;
    confirm against a live account before go-live.
    """
    return json.dumps(
        {"uuid": conversation_id, "comment": {"body": body}}
    ).encode("utf-8")


def _urllib_post(*, url: str, headers: dict, body: bytes) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310 (fixed https host)
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def make_textline_reply_sender(
    *,
    config: Optional[TextlineConfig] = None,
    transport: Optional[Transport] = None,
) -> Callable[[str, str], None]:
    """Build the production ``ReplySender`` for Textline outbound sends.

    The returned ``(conversation_id, body)`` callable POSTs the message to the bound
    Textline conversation. ``config`` defaults to :func:`resolve_textline_config`
    (resolved per send so a token rotation is picked up); ``transport`` injects a
    fake in tests. A non-2xx status raises :class:`TextlineSendError`.
    """
    post = transport or _urllib_post

    def send(conversation_id: str, body: str) -> None:
        resolved = config or resolve_textline_config()
        url = resolved.base_url.rstrip("/") + "/" + _CONVERSATIONS_PATH
        headers = {
            TEXTLINE_ACCESS_TOKEN_HEADER: resolved.access_token,
            "Content-Type": "application/json",
        }
        status = post(url=url, headers=headers, body=_build_payload(conversation_id, body))
        if not 200 <= status < 300:
            raise TextlineSendError(
                f"Textline rejected the reply to conversation {conversation_id} "
                f"(HTTP {status})."
            )

    return send
