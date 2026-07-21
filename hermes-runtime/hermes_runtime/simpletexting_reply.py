"""Real SimpleTexting outbound ReplySender (ADR-0066/0083/0104, ADR-0020).

The gateway delivers one customer-facing reply per turn through a ``ReplySender``
``(conversation_id, body)``. SimpleTexting has no conversation resource — a thread
is keyed by the contact's phone number, so the gateway's ``conversation_id`` IS the
contact phone (set by the inbound webhook normalization). In production the send is
the SimpleTexting API v2:

    POST {base_url}/api/messages
    Authorization: Bearer <API token>
    {"contactPhone": "<digits>", "text": "<message text>", "mode": "AUTO",
     "accountPhone": "<optional sending number>"}

The HTTP transport is injected (default: stdlib ``urllib.request``, no new runtime
dependency) so the sender is unit-testable without the network. A non-2xx response
raises :class:`SimpleTextingSendError`: a failed delivery must surface to the
caller, never be silently dropped (ADR-0104) or reported as a success (ADR-0020).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

# SimpleTexting hosted REST API v2; overridable for a proxy via env.
SIMPLETEXTING_DEFAULT_BASE_URL = "https://api-app2.simpletexting.com/v2/"

_MESSAGES_PATH = "api/messages"

_API_TOKEN_ENV = "SIMPLETEXTING_API_TOKEN"
_BASE_URL_ENV = "SIMPLETEXTING_API_BASE_URL"
_ACCOUNT_PHONE_ENV = "SIMPLETEXTING_ACCOUNT_PHONE"

_NON_DIGITS = re.compile(r"\D")

# Socket timeout for one outbound send. urlopen defaults to no timeout, so a hung
# provider connection would block the dispatch thread that owns the turn forever.
# ponytail: fixed value; make it env-tunable only if a real deploy needs it.
SEND_TIMEOUT_SECONDS = 15

# (url, headers, body) -> HTTP status code. Injected in tests; the default below
# performs the real POST.
Transport = Callable[..., int]


class SimpleTextingSendError(RuntimeError):
    """A SimpleTexting outbound send failed (non-2xx response or transport error)."""


@dataclass(frozen=True)
class SimpleTextingConfig:
    """Resolved SimpleTexting connection for outbound sends."""

    base_url: str
    api_token: str
    account_phone: str = ""


def resolve_simpletexting_config() -> SimpleTextingConfig:
    """Resolve the SimpleTexting connection from the environment (fail-closed).

    Raises ``ValueError`` when ``SIMPLETEXTING_API_TOKEN`` is missing or blank: a
    missing token is a deploy misconfiguration, never a silent unauthed send.
    ``SIMPLETEXTING_ACCOUNT_PHONE`` is optional — when unset, SimpleTexting sends
    from the account's primary number.
    """
    api_token = (os.environ.get(_API_TOKEN_ENV) or "").strip()
    if not api_token:
        raise ValueError(
            f"{_API_TOKEN_ENV} is required to send SimpleTexting replies "
            "(ADR-0083); set it in the environment."
        )
    base_url = (
        os.environ.get(_BASE_URL_ENV) or ""
    ).strip() or SIMPLETEXTING_DEFAULT_BASE_URL
    account_phone = (os.environ.get(_ACCOUNT_PHONE_ENV) or "").strip()
    return SimpleTextingConfig(
        base_url=base_url, api_token=api_token, account_phone=account_phone
    )


def _contact_phone(conversation_id: str) -> str:
    """SimpleTexting wants bare digits (e.g. ``17786803250``), not E.164 ``+``."""
    return _NON_DIGITS.sub("", conversation_id)


def _build_payload(*, contact_phone: str, body: str, account_phone: str) -> bytes:
    payload = {
        "contactPhone": contact_phone,
        "text": body,
        # AUTO lets SimpleTexting pick SMS/EXTENDED_SMS/MMS from the content.
        "mode": "AUTO",
    }
    if account_phone:
        payload["accountPhone"] = _NON_DIGITS.sub("", account_phone)
    return json.dumps(payload).encode("utf-8")


def _urllib_post(*, url: str, headers: dict, body: bytes) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(  # noqa: S310 (https host from config)
            request, timeout=SEND_TIMEOUT_SECONDS
        ) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError) as exc:
        # DNS failure, refused connection, or the socket timeout above. HTTPError
        # subclasses URLError, so it must be caught first. Without this the raw
        # urllib exception escaped a sender documented to raise
        # SimpleTextingSendError, and callers mapping that to a governed
        # vendor_timeout error never saw the actual vendor timeout.
        raise SimpleTextingSendError(f"SimpleTexting request failed: {exc}") from exc


def make_simpletexting_reply_sender(
    *,
    config: Optional[SimpleTextingConfig] = None,
    transport: Optional[Transport] = None,
) -> Callable[[str, str], None]:
    """Build the production ``ReplySender`` for SimpleTexting outbound sends.

    The returned ``(conversation_id, body)`` callable POSTs the message to the
    contact phone the conversation is bound to. ``config`` defaults to
    :func:`resolve_simpletexting_config` (resolved per send so a token rotation is
    picked up); ``transport`` injects a fake in tests. A non-2xx status raises
    :class:`SimpleTextingSendError`.
    """
    post = transport or _urllib_post

    def send(conversation_id: str, body: str) -> None:
        resolved = config or resolve_simpletexting_config()
        url = resolved.base_url.rstrip("/") + "/" + _MESSAGES_PATH
        headers = {
            "Authorization": f"Bearer {resolved.api_token}",
            "Content-Type": "application/json",
        }
        status = post(
            url=url,
            headers=headers,
            body=_build_payload(
                contact_phone=_contact_phone(conversation_id),
                body=body,
                account_phone=resolved.account_phone,
            ),
        )
        if not 200 <= status < 300:
            raise SimpleTextingSendError(
                f"SimpleTexting rejected the reply to {conversation_id} "
                f"(HTTP {status})."
            )

    return send
