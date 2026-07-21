"""Mock toee_sms_reply handlers (ports mock/sms-reply.ts).

`send_message` captures the outbound SMS into an in-memory outbox and
returns a deterministic record. It performs NO network/external call — the
capture is the side effect Launch Eval and the Copilot Workbench audit inspect
(ADR-0066). Exercised through `execute_tool` so the governed boundary is covered
end-to-end.
"""

import re
import socket

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.sms_reply import (
    SmsReplyMockData,
    create_sms_reply_mock_handlers,
)
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external")


def _send(params: dict, data: SmsReplyMockData | None = None):
    """Run send_message through the governed boundary; return (result, data)."""
    data = data if data is not None else SmsReplyMockData()
    driver = MockDriver(create_sms_reply_mock_handlers(data))
    result = execute_tool(
        tool="toee_sms_reply",
        action="send_message",
        params=params,
        context=_ctx(),
        driver=driver,
    )
    return result, data


def test_send_message_returns_captured_outbound_message() -> None:
    result, _ = _send(
        {"conversation_id": "conv_1", "body": "Thanks, your order ships today."}
    )

    assert result.ok is True
    assert result.data["conversation_id"] == "conv_1"
    assert result.data["body"] == "Thanks, your order ships today."
    assert isinstance(result.data["message_id"], str)
    # No media supplied -> media_url omitted entirely (faithful to TS).
    assert "media_url" not in result.data


def test_send_message_reads_camelcase_param_aliases() -> None:
    # TS readString accepts camelCase; the Python port keeps that compatibility
    # while emitting snake_case output keys.
    result, _ = _send(
        {
            "conversationId": "conv_camel",
            "body": "Camel in, snake out.",
            "mediaUrl": "https://cdn.example/wheel.jpg",
        }
    )

    assert result.ok is True
    assert result.data["conversation_id"] == "conv_camel"
    assert result.data["media_url"] == "https://cdn.example/wheel.jpg"


def test_send_message_captures_outbound_in_injected_outbox() -> None:
    result, data = _send({"conversation_id": "conv_7", "body": "On its way!"})

    assert result.ok is True
    assert len(data.outbox) == 1
    assert data.outbox[0]["conversation_id"] == "conv_7"
    assert data.outbox[0]["body"] == "On its way!"


def test_send_message_echoes_media_url_for_product_media_reply() -> None:
    result, _ = _send(
        {
            "conversation_id": "conv_9",
            "body": "Here is that tire.",
            "media_url": "https://cdn.example/tire.jpg",
        }
    )

    assert result.ok is True
    assert result.data["conversation_id"] == "conv_9"
    assert result.data["body"] == "Here is that tire."
    assert result.data["media_url"] == "https://cdn.example/tire.jpg"


def test_send_message_is_deterministic_for_identical_input() -> None:
    params = {"conversation_id": "conv_5", "body": "Same message"}

    first, _ = _send(params)
    second, _ = _send(params)

    assert first.ok is True and second.ok is True
    # No clock/random in the message-id derivation -> identical input, identical id.
    assert first.data == second.data
    assert re.fullmatch(r"msg_[0-9a-f]{8}", first.data["message_id"])


def test_send_message_performs_no_network_call(monkeypatch) -> None:
    # Faithful port of the TS fetch-spy assertion: capture-only, never opens a
    # socket. A socket attempt would be caught by dispatch and flip ok to False.
    def _boom(*args, **kwargs):
        raise AssertionError("send_message must not open a network socket")

    monkeypatch.setattr(socket, "socket", _boom)

    result, data = _send({"conversation_id": "conv_2", "body": "No network here."})

    assert result.ok is True
    assert len(data.outbox) == 1


def test_unregistered_tool_is_governed_configuration_missing() -> None:
    # The sms-reply-only registry has no toee_shopify_read handler; the driver must
    # surface a governed failure, not raise (ADR-0020). TS sms-reply defines no
    # in-handler failure, so this exercises the framework's governed boundary.
    driver = MockDriver(create_sms_reply_mock_handlers(SmsReplyMockData()))

    result = execute_tool(
        tool="toee_shopify_read",
        action="get_order",
        params={"order_id": "1"},
        context=_ctx(),
        driver=driver,
    )

    assert result.ok is False
    assert result.error_class == "configuration_missing"
