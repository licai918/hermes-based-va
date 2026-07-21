"""Canonical inbound normalization tests (ADR-0102).

Ports services/hermes-gateway normalize-inbound.test.ts: E.164 normalization and
building the canonical InboundChannelEvent (fixed channel/provider, media only
when present and non-empty).
"""

from __future__ import annotations

from toee_hermes.gateway.normalize import (
    InboundChannelEvent,
    SmsInboundFields,
    normalize_e164,
    to_inbound_channel_event,
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


def _fields(**overrides) -> SmsInboundFields:
    base = dict(
        event_id="evt_1",
        conversation_id="conv_9",
        from_phone="(519) 555-0123",
        body="where is my order?",
        received_at="2026-06-19T12:00:00.000Z",
        raw_event_type="message:received",
    )
    base.update(overrides)
    return SmsInboundFields(**base)


def test_builds_canonical_event() -> None:
    assert to_inbound_channel_event(_fields()) == InboundChannelEvent(
        channel="simpletexting_sms",
        provider="simpletexting",
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
