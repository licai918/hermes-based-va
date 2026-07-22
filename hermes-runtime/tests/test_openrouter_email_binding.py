"""S17 (⚠️ highest-risk): an email turn binds Customer Memory on the EMAIL identity.

``openrouter.py`` used to hardcode ``channel="sms"`` in ``_with_channel_identity``,
which feeds the Customer Memory binding key. An email turn MUST carry the email
channel here, or it computes the WRONG binding key and silently reads/writes another
binding's memory (a governance/privacy bug). These tests pin the fix: the turn-time
read is issued against ``provisional:email:<address>``, never a phone/sms key.
"""

from __future__ import annotations

from types import SimpleNamespace

from toee_hermes.drivers.mock.memory import binding_key_from_identity
from toee_hermes.gateway.normalize import SIMULATED_EMAIL

from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    _with_channel_identity,
    make_openrouter_run_turn,
)

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)
_ADDRESS = "Accounts@Acme-Fleet.Example"  # mixed case: canonicalization must lower it


class _RecordingStore:
    """Records every binding_key the turn's memory read is issued against."""

    def __init__(self) -> None:
        self.read_keys: list[str] = []

    def load_customer_memory(self, binding_key: str):
        self.read_keys.append(binding_key)
        return []


def _run_email_turn(monkeypatch, *, store, channel=SIMULATED_EMAIL) -> None:
    import hermes_runtime.openrouter as openrouter_mod

    monkeypatch.setenv("TOOL_BACKEND", "datastore")  # memory_enabled() -> True

    def capture(**_kwargs):
        return {"final_response": "", "messages": []}

    monkeypatch.setattr(openrouter_mod, "run_agent_turn", capture)
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=store,
    )
    context = SimpleNamespace(
        conversation_id="conv-email-1",
        sms_session_id=None,
        from_phone=_ADDRESS,  # channel-identity slot carries the From address
        session_identity_snapshot=None,  # unmatched sender -> provisional binding
        channel=channel,
    )
    run_turn(context, "Any update on my order?")


def test_with_channel_identity_uses_email_channel_and_canonical_address() -> None:
    merged = _with_channel_identity(None, _ADDRESS, SIMULATED_EMAIL)
    assert merged["channel"] == "email"
    assert merged["channel_identity"] == "accounts@acme-fleet.example"


def test_email_binding_key_is_email_shaped_not_phone() -> None:
    merged = _with_channel_identity(None, _ADDRESS, SIMULATED_EMAIL)
    resolved = binding_key_from_identity(merged)
    assert resolved == ("provisional:email:accounts@acme-fleet.example", "provisional")


def test_email_turn_reads_the_email_binding_not_an_sms_binding(monkeypatch) -> None:
    store = _RecordingStore()
    _run_email_turn(monkeypatch, store=store)
    assert store.read_keys == ["provisional:email:accounts@acme-fleet.example"]
    # The bug this slice neutralizes: no sms-shaped key is ever read for an email turn.
    assert all(not key.startswith("provisional:sms:") for key in store.read_keys)


def test_sms_turn_still_binds_on_the_phone_channel(monkeypatch) -> None:
    # Regression guard: the default (SMS) path is unchanged — E.164 phone key.
    store = _RecordingStore()

    import hermes_runtime.openrouter as openrouter_mod

    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setattr(
        openrouter_mod, "run_agent_turn", lambda **_k: {"final_response": "", "messages": []}
    )
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=store,
    )
    context = SimpleNamespace(
        conversation_id="conv-sms-1",
        sms_session_id=None,
        from_phone="+14165550175",
        session_identity_snapshot=None,
        channel="simpletexting_sms",
    )
    run_turn(context, "hi")
    assert store.read_keys == ["provisional:sms:+14165550175"]
