"""S11: per-turn Customer Memory observability + visible error swallows (PRD §6.4).

So a real conversation can be audited after the fact ("did this customer get
*their* memory?") without ever logging PII, the async turn (``run_turn``) emits one
compact log line per turn: the resolved ``binding_key``, the injected slot NAMES
only (never values), and whether the S10 provisional->verified merge fired. The two
previously-silent failure swallows (the S07 read and the S10 merge trigger) must
also surface a WARNING instead of failing invisibly.

Same scaffolding shape as ``test_openrouter_memory_injection.py`` /
``test_openrouter_provisional_merge.py`` (scripted provider, a fake store,
``run_agent_turn`` stubbed) — a fake store here instead of real Postgres, since
these tests are about what gets logged, not the datastore round-trip itself
(already proven by S07/S10).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from toee_hermes.gateway.ingress import SessionIdentitySnapshot

from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
)

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)

_SHOPIFY_ID = "gid://shopify/Customer/90909"
_PROVISIONAL_PHONE = "+14165550190"
_SLOT_NAME = "contact_time_preference"
# PII surface: a slot VALUE must never reach any log record (only the slot NAME may).
_SECRET_SLOT_VALUE = "text me after 5pm, don't call — VIN 1HGCM82633A004352"


class _ScriptedMemoryStore:
    """Canned memory + a fired merge, without touching Postgres."""

    def merge_provisional_memory(self, provisional_key, verified_key):
        return {"moved": ["delivery_habit_note"], "overridden": {}}

    def load_customer_memory(self, binding_key):
        return [{"slot": _SLOT_NAME, "value": _SECRET_SLOT_VALUE}]


class _ReadRaisingStore:
    """The read explodes; merge must never be reached for an unmatched caller."""

    def load_customer_memory(self, binding_key):
        raise RuntimeError("read boom")

    def merge_provisional_memory(self, *a, **k):  # pragma: no cover - must not run
        raise AssertionError("merge_provisional_memory must not be called")


class _MergeRaisingStore:
    """The merge explodes; the read must still run afterward (turn still completes)."""

    def merge_provisional_memory(self, *a, **k):
        raise RuntimeError("merge boom")

    def load_customer_memory(self, binding_key):
        return []


def _run_turn(monkeypatch, *, store, context, inbound_body="Hi again"):
    """Run ``run_turn`` with ``run_agent_turn`` stubbed; return the injected message."""
    import hermes_runtime.openrouter as openrouter_mod

    captured: dict[str, str] = {}

    def capture(*, user_message: str, **_kwargs: object) -> dict[str, object]:
        captured["user_message"] = user_message
        return {"final_response": "", "messages": []}

    monkeypatch.setattr(openrouter_mod, "run_agent_turn", capture)
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=store,
    )
    run_turn(context, inbound_body)
    return captured["user_message"]


def _verified_context(*, conversation_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id=conversation_id,
        sms_session_id=None,
        from_phone=_PROVISIONAL_PHONE,
        session_identity_snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at="2026-07-13T00:00:00Z",
            shopify_customer_id=_SHOPIFY_ID,
            display_name="Obs Co",
        ),
    )


def test_turn_with_memory_logs_binding_key_slots_and_merge_fired_no_value_leak(
    monkeypatch, caplog
) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    caplog.set_level(logging.INFO)

    user_message = _run_turn(
        monkeypatch,
        store=_ScriptedMemoryStore(),
        context=_verified_context(conversation_id="conv-obs-memory"),
    )

    # Sanity: the slot value really was injected into the prompt this turn.
    assert _SECRET_SLOT_VALUE in user_message

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        _SHOPIFY_ID in msg and _SLOT_NAME in msg and "merge_fired=True" in msg
        for msg in messages
    ), messages

    # The crux: no slot VALUE ever reaches a log record.
    assert not any(_SECRET_SLOT_VALUE in msg for msg in messages)


def test_read_error_logs_warning_and_turn_still_completes(monkeypatch, caplog) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    caplog.set_level(logging.WARNING)

    context = SimpleNamespace(
        conversation_id="conv-obs-read-error",
        sms_session_id=None,
        from_phone=_PROVISIONAL_PHONE,
        session_identity_snapshot=None,  # unmatched -> provisional binding
    )

    user_message = _run_turn(monkeypatch, store=_ReadRaisingStore(), context=context)

    # FR-7: the turn still completes and degrades to no memory block, never raises.
    assert "Customer Memory" not in user_message

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "read" in warnings[0].getMessage().lower()


def test_merge_error_logs_warning_and_turn_still_completes(monkeypatch, caplog) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    caplog.set_level(logging.WARNING)

    user_message = _run_turn(
        monkeypatch,
        store=_MergeRaisingStore(),
        context=_verified_context(conversation_id="conv-obs-merge-error"),
    )

    # FR-7: the merge hiccup never fails the reply; the read still runs afterward.
    assert "Customer Memory" not in user_message

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "merge" in warnings[0].getMessage().lower()
