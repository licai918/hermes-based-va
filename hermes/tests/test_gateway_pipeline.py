"""Inbound pipeline orchestrator tests (ADR-0104, ADR-0108, ADR-0109, ADR-0043).

Composes the gateway primitives into one decision the route layer acts on:
verify -> normalize -> idempotency -> opt-out -> rate-limit -> ingress -> accept.
Mirrors the P0 gateway pipeline contract: signature fail 401, STOP short-circuit,
duplicate ignore, rate-limit 200-no-enqueue, ingress transient 500, else enqueue.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from toee_hermes.drivers.mock import MockDriver, create_identity_mock_handlers
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import ToolRequest
from toee_hermes.gateway.normalize import TextlineInboundFields
from toee_hermes.gateway.opt_out import SMS_OPT_OUT_CONFIRMATION
from toee_hermes.gateway.pipeline import process_inbound
from toee_hermes.gateway.rate_limit import create_inbound_rate_limiter
from toee_hermes.tool_gate import ToolExecutionContext

SECRET = "whsec_textline_test"
RESOLVED_AT = "2026-06-19T12:00:00.000Z"
RAW_BODY = '{"event":"message:received","id":"evt_1"}'


def _sig(body: str = RAW_BODY, key: str = SECRET) -> str:
    return hmac.new(key.encode(), body.encode(), hashlib.sha256).hexdigest()


def _fields(**overrides: Any) -> TextlineInboundFields:
    base = dict(
        event_id="evt_1",
        conversation_id="conv_9",
        from_phone="+14165550101",
        body="where is my order?",
        received_at=RESOLVED_AT,
        raw_event_type="message:received",
    )
    base.update(overrides)
    return TextlineInboundFields(**base)


def _identity_driver() -> MockDriver:
    return MockDriver(create_identity_mock_handlers())


def _process(**overrides: Any):
    kwargs: dict[str, Any] = dict(
        raw_body=RAW_BODY,
        signature=_sig(),
        secret=SECRET,
        fields=_fields(),
        driver=_identity_driver(),
        rate_limiter=create_inbound_rate_limiter(),
        resolved_at=RESOLVED_AT,
        at_ms=0,
    )
    kwargs.update(overrides)
    return process_inbound(**kwargs)


def test_invalid_signature_rejected_401() -> None:
    decision = _process(signature="deadbeef")
    assert decision.status == 401
    assert decision.action == "reject"
    assert decision.stage == "verify"
    assert decision.enqueue is False
    assert decision.event is None


def test_stop_short_circuits_with_confirmation() -> None:
    decision = _process(fields=_fields(body="STOP"))
    assert decision.status == 200
    assert decision.action == "opt_out"
    assert decision.stage == "opt_out"
    assert decision.enqueue is False
    assert decision.reply == SMS_OPT_OUT_CONFIRMATION


def test_duplicate_event_ignored_200() -> None:
    decision = _process(is_duplicate=lambda event_id: event_id == "evt_1")
    assert decision.status == 200
    assert decision.action == "duplicate"
    assert decision.stage == "idempotency"
    assert decision.enqueue is False


def test_verified_message_accepted_and_enqueued() -> None:
    decision = _process()
    assert decision.status == 200
    assert decision.action == "enqueue"
    assert decision.stage == "accept"
    assert decision.enqueue is True
    assert decision.event is not None
    assert decision.event.from_phone == "+14165550101"
    assert decision.snapshot is not None
    assert decision.snapshot.outcome == "verified_customer"


def test_unmatched_message_still_enqueued() -> None:
    decision = _process(fields=_fields(from_phone="+15195550000"))
    assert decision.status == 200
    assert decision.action == "enqueue"
    assert decision.snapshot is not None
    assert decision.snapshot.outcome == "unmatched_caller"


def test_rate_limited_persists_but_skips_enqueue() -> None:
    limiter = create_inbound_rate_limiter(limit=1, window_ms=1000)
    first = _process(rate_limiter=limiter, fields=_fields(event_id="e1"))
    assert first.action == "enqueue"
    second = _process(rate_limiter=limiter, fields=_fields(event_id="e2"))
    assert second.status == 200
    assert second.action == "rate_limited"
    assert second.stage == "rate_limit"
    assert second.enqueue is False
    assert second.event is not None  # still persisted for audit/Copilot context
    # ADR-0109 skips only the enqueue: the turn is still ingress-resolved.
    assert second.snapshot is not None
    assert second.snapshot.outcome == "verified_customer"


class _FailingDriver:
    kind = "mock"

    def execute(self, request: ToolRequest, context: ToolExecutionContext) -> Any:
        raise ToolDriverError("vendor_timeout", "match_phone upstream 503")


def test_ingress_transient_failure_is_retryable_500() -> None:
    decision = _process(driver=_FailingDriver())
    assert decision.status == 500
    assert decision.action == "retry"
    assert decision.stage == "ingress"
    assert decision.retryable is True
    assert decision.enqueue is False
