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


def simpletexting_configured() -> bool:
    """Whether ``SIMPLETEXTING_API_TOKEN`` is present (for the S15/S16 health surface).

    Mirrors ``easyroutes_configured``/``gadget_configured``: env-presence only, no
    token value ever returned. The S16 probe reuses this before a live token check.
    """
    return bool((os.environ.get(_API_TOKEN_ENV) or "").strip())


# S16 health probe: an authenticated READ that validates the token WITHOUT sending
# a message (never an outbound send on the health surface). UNVERIFIED against the
# live API (owner-blocked: the token is not in the env yet) -- the exact account/
# read endpoint is a wire detail to confirm at cutover, isolated here. A non-2xx
# (esp. 401/403 for a rotated token) or a transport error is a FAILURE.
_TOKEN_PROBE_PATH = "api/account"
_PROBE_TIMEOUT_SECONDS = 8.0


def probe_simpletexting_token() -> None:
    """S16 probe: validate the SimpleTexting token via an authenticated read.

    Raises on any fault. Reads only -- never a send, never a customer's data.
    """
    config = resolve_simpletexting_config()  # raises ValueError when token absent
    url = config.base_url.rstrip("/") + "/" + _TOKEN_PROBE_PATH
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {config.api_token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 (https host from config)
            request, timeout=_PROBE_TIMEOUT_SECONDS
        ) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        raise SimpleTextingSendError(
            f"SimpleTexting token check returned HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SimpleTextingSendError(
            f"SimpleTexting token check failed: {exc}"
        ) from exc
    if not 200 <= status < 300:
        raise SimpleTextingSendError(
            f"SimpleTexting token check returned HTTP {status}"
        )


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
