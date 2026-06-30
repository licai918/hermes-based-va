"""Real Textline outbound ReplySender (ADR-0066/0083/0104, ADR-0020).

The gateway delivers one customer-facing reply per turn through a ``ReplySender``
``(conversation_id, body)``. In production that send is the Textline REST API:

    POST {base_url}/api/conversation/{conversation_uuid}.json
    X-TGP-ACCESS-TOKEN: <Textline Developer API access token>
    {"comment": {"body": "<message text>"}}

``api/conversations.json`` (plural) is the "message a phone number" action and
requires ``phone_number``; replying inside an existing thread uses the singular
``api/conversation/{uuid}.json`` route (Textline Developer API / textline-php).

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

def _conversation_message_path(conversation_id: str) -> str:
    return f"api/conversation/{conversation_id}.json"

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


def _build_payload(body: str) -> bytes:
    """Serialize the reply body for ``POST api/conversation/{uuid}.json``."""
    return json.dumps({"comment": {"body": body}}).encode("utf-8")


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
        url = resolved.base_url.rstrip("/") + "/" + _conversation_message_path(
            conversation_id
        )
        headers = {
            TEXTLINE_ACCESS_TOKEN_HEADER: resolved.access_token,
            "Content-Type": "application/json",
        }
        status = post(url=url, headers=headers, body=_build_payload(body))
        if not 200 <= status < 300:
            raise TextlineSendError(
                f"Textline rejected the reply to conversation {conversation_id} "
                f"(HTTP {status})."
            )

    return send
