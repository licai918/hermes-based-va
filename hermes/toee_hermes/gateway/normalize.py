"""Canonical inbound normalization for the SMS gateway pipeline (ADR-0102).

The provider-specific JSON shape and accepted/ignored event classification are
extracted by the route layer; this module owns the schema-independent canonical
pieces: E.164 phone normalization and building the InboundChannelEvent the rest
of the system consumes. SimpleTexting has no conversation resource, so the
canonical ``conversation_id`` is the contact's E.164 phone — the outbound
ReplySender sends to that same phone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

_NON_DIGITS = re.compile(r"\D")


@dataclass(frozen=True)
class SmsInboundFields:
    """Extracted provider inbound fields, provider key names already resolved."""

    event_id: str
    conversation_id: str
    from_phone: str
    body: str
    received_at: str
    raw_event_type: str
    media_urls: Optional[list[str]] = None


@dataclass(frozen=True)
class InboundChannelEvent:
    """Canonical inbound channel event consumed by the rest of the system."""

    channel: Literal["simpletexting_sms"]
    provider: Literal["simpletexting"]
    event_id: str
    conversation_id: str
    from_phone: str
    body: str
    received_at: str
    raw_event_type: str
    media_urls: Optional[list[str]] = None


def normalize_e164(input: str) -> str:
    """Normalize a phone string to E.164.

    A leading ``+`` is authoritative (international); otherwise a bare 10-digit
    number is assumed North American (``+1``) and an 11-digit ``1``-prefixed
    number is promoted to ``+1...``.
    """
    trimmed = input.strip()
    has_plus = trimmed.startswith("+")
    digits = _NON_DIGITS.sub("", trimmed)
    if has_plus:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}"


def to_inbound_channel_event(fields: SmsInboundFields) -> InboundChannelEvent:
    media_urls = (
        fields.media_urls if fields.media_urls else None
    )
    return InboundChannelEvent(
        channel="simpletexting_sms",
        provider="simpletexting",
        event_id=fields.event_id,
        conversation_id=fields.conversation_id,
        from_phone=normalize_e164(fields.from_phone),
        body=fields.body,
        received_at=fields.received_at,
        raw_event_type=fields.raw_event_type,
        media_urls=media_urls,
    )
