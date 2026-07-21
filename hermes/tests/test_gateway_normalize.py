"""Canonical inbound normalization tests (ADR-0102).

Ports services/hermes-gateway normalize-inbound.test.ts: E.164 normalization and
building the canonical InboundChannelEvent (fixed channel/provider, media only
when present and non-empty).
"""

from __future__ import annotations

from toee_hermes.gateway.normalize import (
    InboundChannelEvent,
    TextlineInboundFields,
    canonicalize_email,
    normalize_e164,
    to_inbound_channel_event,
    to_inbound_email_event,
)


def test_passes_through_well_formed_e164() -> None:
    assert normalize_e164("+15195550123") == "+15195550123"


def test_adds_plus1_for_bare_10_digit() -> None:
    assert normalize_e164("5195550123") == "+15195550123"


def test_adds_plus_for_11_digit_leading_1() -> None:
    assert normalize_e164("15195550123") == "+15195550123"


def test_strips_spaces_dashes_parens_dots() -> None:
    assert normalize_e164("(519) 555-0123") == "+15195550123"
    assert normalize_e164("519.555.0123") == "+15195550123"


def test_keeps_leading_plus_for_international() -> None:
    assert normalize_e164("+44 20 7946 0958") == "+442079460958"


def _fields(**overrides) -> TextlineInboundFields:
    base = dict(
        event_id="evt_1",
        conversation_id="conv_9",
        from_phone="(519) 555-0123",
        body="where is my order?",
        received_at="2026-06-19T12:00:00.000Z",
        raw_event_type="message:received",
    )
    base.update(overrides)
    return TextlineInboundFields(**base)


def test_builds_canonical_event() -> None:
    assert to_inbound_channel_event(_fields()) == InboundChannelEvent(
        channel="textline_sms",
        provider="textline",
        event_id="evt_1",
        conversation_id="conv_9",
        from_phone="+15195550123",
        body="where is my order?",
        received_at="2026-06-19T12:00:00.000Z",
        raw_event_type="message:received",
        media_urls=None,
    )


def test_media_urls_only_when_present_and_nonempty() -> None:
    assert to_inbound_channel_event(_fields(media_urls=[])).media_urls is None
    assert to_inbound_channel_event(
        _fields(media_urls=["https://cdn/x.jpg"])
    ).media_urls == ["https://cdn/x.jpg"]


# --- S17: simulated email normalization (FR-18) ------------------------------


def test_canonicalize_email_trims_and_lowercases() -> None:
    assert canonicalize_email("  Accounts@Acme-Fleet.Example ") == "accounts@acme-fleet.example"


def test_builds_canonical_email_event_folding_subject_into_body() -> None:
    event = to_inbound_email_event(
        event_id="evt-e1",
        conversation_id="conv-e1",
        from_address="Accounts@Acme-Fleet.Example",
        subject="Order 10444",
        body="Where is it?",
        received_at="2026-06-19T12:00:00.000Z",
    )
    assert event == InboundChannelEvent(
        channel="simulated_email",
        provider="simulated_email",
        event_id="evt-e1",
        conversation_id="conv-e1",
        from_phone="accounts@acme-fleet.example",
        body="Subject: Order 10444\n\nWhere is it?",
        received_at="2026-06-19T12:00:00.000Z",
        raw_event_type="email.received",
        media_urls=None,
    )


def test_email_event_without_subject_keeps_body_verbatim() -> None:
    event = to_inbound_email_event(
        event_id="evt-e2",
        conversation_id="conv-e2",
        from_address="a@b.com",
        subject="",
        body="just the body",
        received_at="2026-06-19T12:00:00.000Z",
    )
    assert event.body == "just the body"
