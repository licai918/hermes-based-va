"""Mock handlers for ``toee_textline_reply`` (ports mock/textline.ts, ADR-0066).

``send_message`` captures the outbound Textline SMS into an in-memory outbox and
returns a deterministic record. It performs NO network/external call — the
capture is the side effect Launch Eval and the Copilot Workbench audit inspect.
Optional ``media_url`` supports Product Media Reply. Data is injectable so the
Launch Eval fixture loader can give each scenario a fresh, isolated outbox.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .driver import MockHandlerRegistry


@dataclass(frozen=True)
class TextlineMockData:
    # Captured outbound messages, in send order. The eval fixture loader inspects
    # this to assert what Hermes sent in the current SMS Session. ``frozen`` pins
    # the binding; the list itself is appended to on capture.
    outbox: list[dict[str, Any]] = field(default_factory=list)
    # Prefix for the deterministic message_id.
    message_id_prefix: str = "msg"


def create_textline_mock_data() -> TextlineMockData:
    """Fresh, isolated mock data so captured messages never leak across runs."""
    return TextlineMockData()


# Shared baseline singleton (mirrors textlineBaselineData). Tests and scenarios
# that assert outbox contents should pass a fresh ``TextlineMockData`` instead.
textline_baseline_data = create_textline_mock_data()


def _read_string(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _deterministic_id(prefix: str, parts: tuple[str | None, ...]) -> str:
    """Deterministic 32-bit FNV-1a hash rendered as an 8-char hex suffix.

    No clock or randomness, so an identical send always yields the same
    message_id (faithful to the TS ``Math.imul`` FNV-1a derivation).
    """
    text = "|".join(part if part is not None else "" for part in parts)
    hash_value = 0x811C9DC5
    for char in text:
        hash_value ^= ord(char)
        hash_value = (hash_value * 0x01000193) & 0xFFFFFFFF
    return f"{prefix}_{hash_value:08x}"


def _send_message(data: TextlineMockData, params: dict[str, Any]) -> dict[str, Any]:
    conversation_id = _read_string(params, "conversation_id", "conversationId") or ""
    body = _read_string(params, "body") or ""
    media_url = _read_string(params, "media_url", "mediaUrl")

    message: dict[str, Any] = {
        "message_id": _deterministic_id(
            data.message_id_prefix, (conversation_id, body, media_url)
        ),
        "conversation_id": conversation_id,
        "body": body,
    }
    if media_url is not None:
        message["media_url"] = media_url

    # Capture only — never call Textline or any external API.
    data.outbox.append(message)
    return message


def create_textline_mock_handlers(
    data: TextlineMockData = textline_baseline_data,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific data set.

    The Launch Eval fixture loader passes per-scenario data; the default uses the
    shared baseline outbox.
    """
    # send_message *produces* an outbound capture from raw reply params, so the
    # handler reads only ``params`` and ignores ``context``.
    return {
        "toee_textline_reply": {
            "send_message": lambda params, context: _send_message(data, params),
        }
    }


textline_mock_handlers: MockHandlerRegistry = create_textline_mock_handlers()
