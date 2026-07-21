"""Canonical inbound normalization for the SMS/email pipeline (ADR-0102).

The provider-specific JSON shape and accepted/ignored event classification are
extracted by the route layer; this module owns the schema-independent canonical
pieces: E.164 phone normalization, email canonicalization, and building the
InboundChannelEvent the rest of the system consumes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

_NON_DIGITS = re.compile(r"\D")

# Ingress channel literals (ADR-0102, 0.0.3 S17/FR-18, ADR-0153). ``simpletexting_sms``
# is the SMS channel; ``simulated_email`` is the simulator-driven email channel (RK-4:
# no real email provider). Both are plain strings in the DB channel columns (TEXT NOT
# NULL, no enum CHECK) — and the persisted vocabulary is ``sms``|``email`` anyway — so
# the provider rename needed no migration.
SIMPLETEXTING_SMS = "simpletexting_sms"
SIMULATED_EMAIL = "simulated_email"


def is_email_channel(channel: str) -> bool:
    """Whether a channel value denotes email, across BOTH vocabularies (S17).

    Ingress events carry ``simulated_email``; the persisted identity/read-model
    vocabulary uses ``email`` (customer_thread.channel, identity_link.channel,
    CaseChannel). A single predicate over both keeps the pipeline, store keys,
    memory binding, and reply shaping from having to translate between them.
    """
    return channel in (SIMULATED_EMAIL, "email")


@dataclass(frozen=True)
class SmsInboundFields:
    """Extracted inbound SMS fields, provider key names already resolved."""

    event_id: str
    conversation_id: str
    from_phone: str
    body: str
    received_at: str
    raw_event_type: str
    media_urls: Optional[list[str]] = None


@dataclass(frozen=True)
class InboundChannelEvent:
    """Canonical inbound channel event consumed by the rest of the system.

    ``from_phone`` carries the channel identity: an E.164 phone for
    ``simpletexting_sms``, the authenticated From address for ``simulated_email``
    (ADR-0054 — never Reply-To or a body-supplied address). The name is retained
    (rather than renamed to ``from_identity``) to reuse the SMS shape end to end.
    """

    channel: Literal["simpletexting_sms", "simulated_email"]
    provider: Literal["simpletexting", "simulated_email"]
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


def canonicalize_email(input: str) -> str:
    """Canonicalize an email address for identity/binding keys (S17, ADR-0052).

    Trim and lowercase — enough to make the From address a stable binding key so a
    later turn from the same sender resolves the same Customer Memory. Deliberately
    NOT E.164 normalization: :func:`normalize_e164` strips non-digits and would
    destroy an address (``a@b.com`` -> ``+``), so the email channel must never route
    through it.
    """
    return input.strip().lower()


def to_inbound_channel_event(fields: SmsInboundFields) -> InboundChannelEvent:
    media_urls = (
        fields.media_urls if fields.media_urls else None
    )
    return InboundChannelEvent(
        channel=SIMPLETEXTING_SMS,
        provider="simpletexting",
        event_id=fields.event_id,
        conversation_id=fields.conversation_id,
        from_phone=normalize_e164(fields.from_phone),
        body=fields.body,
        received_at=fields.received_at,
        raw_event_type=fields.raw_event_type,
        media_urls=media_urls,
    )


def to_inbound_email_event(
    *,
    event_id: str,
    conversation_id: str,
    from_address: str,
    subject: str,
    body: str,
    received_at: str,
    raw_event_type: str = "email.received",
) -> InboundChannelEvent:
    """Build the canonical inbound event for a simulated email (S17/FR-18).

    Reuses the SMS ``InboundChannelEvent`` shape: the From address is canonicalized
    into ``from_phone`` (the channel-identity slot) and the subject — new vs SMS —
    is prepended to the body so the same governed turn sees it (nothing is dropped).
    """
    subject = (subject or "").strip()
    turn_body = f"Subject: {subject}\n\n{body}" if subject else body
    return InboundChannelEvent(
        channel=SIMULATED_EMAIL,
        provider=SIMULATED_EMAIL,
        event_id=event_id,
        conversation_id=conversation_id,
        from_phone=canonicalize_email(from_address),
        body=turn_body,
        received_at=received_at,
        raw_event_type=raw_event_type,
        media_urls=None,
    )
