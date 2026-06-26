"""Real Textline outbound ReplySender (ADR-0066/0083/0104).

The gateway delivers exactly one customer-facing reply per turn through a
``ReplySender`` (conversation_id, body). In production that send is the Textline
REST API: ``POST https://application.textline.com/api/conversations.json`` with the
conversation UUID + message body, authenticated by the ``X-TGP-ACCESS-TOKEN`` header
(Textline Developer API access token). Sources: dltHub Textline API docs and Ibexa
Connect's "Message a Conversation" action.

The HTTP transport is injected so these tests never touch the network: they assert
the request the sender builds and that a non-2xx response raises (a failed send must
surface, never be silently dropped — ADR-0104 error handling, ADR-0020 no
fabrication). The exact request-body field names are the one contract detail to
confirm against a live Textline account before go-live.
"""

from __future__ import annotations

import json

import pytest

from hermes_runtime.textline_reply import (
    TEXTLINE_ACCESS_TOKEN_HEADER,
    TextlineConfig,
    TextlineSendError,
    make_textline_reply_sender,
    resolve_textline_config,
)

ENV_KEYS = ("TEXTLINE_ACCESS_TOKEN", "TEXTLINE_API_BASE_URL")


@pytest.fixture(autouse=True)
def _clear_textline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class _RecordingTransport:
    """Captures the single POST the sender makes; returns a scripted status."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls: list[dict] = []

    def __call__(self, *, url: str, headers: dict, body: bytes) -> int:
        self.calls.append({"url": url, "headers": headers, "body": body})
        return self.status


def _config() -> TextlineConfig:
    return TextlineConfig(
        base_url="https://application.textline.com/", access_token="tok-123"
    )


# --- G8a: resolve_textline_config -----------------------------------------


def test_resolve_defaults_to_the_textline_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEXTLINE_ACCESS_TOKEN", "tok-123")

    config = resolve_textline_config()

    assert config.access_token == "tok-123"
    assert config.base_url == "https://application.textline.com/"


def test_resolve_reads_a_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXTLINE_ACCESS_TOKEN", "tok-123")
    monkeypatch.setenv("TEXTLINE_API_BASE_URL", "https://proxy.internal/")

    assert resolve_textline_config().base_url == "https://proxy.internal/"


def test_resolve_raises_a_clear_error_when_the_access_token_is_absent() -> None:
    with pytest.raises(ValueError, match="TEXTLINE_ACCESS_TOKEN"):
        resolve_textline_config()


# --- G8b: make_textline_reply_sender --------------------------------------


def test_reply_sender_posts_the_message_to_the_bound_conversation() -> None:
    transport = _RecordingTransport(status=200)
    send = make_textline_reply_sender(config=_config(), transport=transport)

    send("conv-uuid-A", "Your order shipped today.")

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "https://application.textline.com/api/conversations.json"
    assert call["headers"][TEXTLINE_ACCESS_TOKEN_HEADER] == "tok-123"
    assert call["headers"]["Content-Type"] == "application/json"
    payload = json.loads(call["body"].decode("utf-8"))
    assert payload["uuid"] == "conv-uuid-A"
    assert payload["comment"]["body"] == "Your order shipped today."


def test_reply_sender_raises_when_textline_rejects_the_send() -> None:
    transport = _RecordingTransport(status=422)
    send = make_textline_reply_sender(config=_config(), transport=transport)

    with pytest.raises(TextlineSendError):
        send("conv-uuid-A", "Your order shipped today.")
