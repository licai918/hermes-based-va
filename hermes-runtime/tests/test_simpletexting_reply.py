"""Real SimpleTexting outbound ReplySender (ADR-0066/0083/0104).

The gateway delivers exactly one customer-facing reply per turn through a
``ReplySender`` (conversation_id, body). In production that send is the
SimpleTexting API v2: ``POST https://api-app2.simpletexting.com/v2/api/messages``
with ``{"contactPhone", "text", "mode"}``, authenticated by ``Authorization:
Bearer <token>``. The conversation_id IS the contact phone (SimpleTexting has no
conversation resource).

The HTTP transport is injected so these tests never touch the network: they assert
the request the sender builds and that a non-2xx response raises (a failed send
must surface, never be silently dropped — ADR-0104, ADR-0020).
"""

from __future__ import annotations

import json

import pytest

from hermes_runtime.simpletexting_reply import (
    SimpleTextingConfig,
    SimpleTextingSendError,
    make_simpletexting_reply_sender,
    resolve_simpletexting_config,
)

ENV_KEYS = (
    "SIMPLETEXTING_API_TOKEN",
    "SIMPLETEXTING_API_BASE_URL",
    "SIMPLETEXTING_ACCOUNT_PHONE",
)


@pytest.fixture(autouse=True)
def _clear_simpletexting_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class _RecordingTransport:
    """Captures the single POST the sender makes; returns a scripted status."""

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.calls: list[dict] = []

    def __call__(self, *, url: str, headers: dict, body: bytes) -> int:
        self.calls.append({"url": url, "headers": headers, "body": body})
        return self.status


def _config(account_phone: str = "") -> SimpleTextingConfig:
    return SimpleTextingConfig(
        base_url="https://api-app2.simpletexting.com/v2/",
        api_token="tok-123",
        account_phone=account_phone,
    )


# --- resolve_simpletexting_config ------------------------------------------


def test_resolve_defaults_to_the_simpletexting_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLETEXTING_API_TOKEN", "tok-123")

    config = resolve_simpletexting_config()

    assert config.api_token == "tok-123"
    assert config.base_url == "https://api-app2.simpletexting.com/v2/"
    assert config.account_phone == ""


def test_resolve_reads_base_url_and_account_phone_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLETEXTING_API_TOKEN", "tok-123")
    monkeypatch.setenv("SIMPLETEXTING_API_BASE_URL", "https://proxy.internal/")
    monkeypatch.setenv("SIMPLETEXTING_ACCOUNT_PHONE", "9053378266")

    config = resolve_simpletexting_config()

    assert config.base_url == "https://proxy.internal/"
    assert config.account_phone == "9053378266"


def test_resolve_raises_a_clear_error_when_the_api_token_is_absent() -> None:
    with pytest.raises(ValueError, match="SIMPLETEXTING_API_TOKEN"):
        resolve_simpletexting_config()


# --- make_simpletexting_reply_sender ---------------------------------------


def test_reply_sender_posts_the_message_to_the_contact_phone() -> None:
    transport = _RecordingTransport(status=201)
    send = make_simpletexting_reply_sender(config=_config(), transport=transport)

    send("+17786803250", "Your order shipped today.")

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "https://api-app2.simpletexting.com/v2/api/messages"
    assert call["headers"]["Authorization"] == "Bearer tok-123"
    assert call["headers"]["Content-Type"] == "application/json"
    payload = json.loads(call["body"].decode("utf-8"))
    assert payload == {
        "contactPhone": "17786803250",
        "text": "Your order shipped today.",
        "mode": "AUTO",
    }


def test_reply_sender_includes_the_configured_account_phone() -> None:
    transport = _RecordingTransport(status=201)
    send = make_simpletexting_reply_sender(
        config=_config(account_phone="(905) 337-8266"), transport=transport
    )

    send("17786803250", "hi")

    payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
    assert payload["accountPhone"] == "9053378266"


def test_reply_sender_raises_when_simpletexting_rejects_the_send() -> None:
    transport = _RecordingTransport(status=422)
    send = make_simpletexting_reply_sender(config=_config(), transport=transport)

    with pytest.raises(SimpleTextingSendError):
        send("+17786803250", "Your order shipped today.")
