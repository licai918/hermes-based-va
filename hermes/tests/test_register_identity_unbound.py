"""Unbound registration threads identity into the write-binding context (S08).

The Copilot draft turn boots ``internal_copilot`` UNBOUND (no ``conversation_id``,
so via :func:`register`, not :func:`register_turn`). Before S08 that path dropped
identity, so an employee-confirmed correction write had no ``context.identity`` to
bind from and fell back to the 2-part ``provisional:{channel_identity_id}`` carve-out.
Threading ``identity`` through the unbound path aligns the write to the SAME
identity-derived key the turn-time read uses (``binding_key_from_identity``).

``RecordingCtx`` (no global registry) keeps this order-independent.
"""

from __future__ import annotations

import json
from typing import Any

from toee_hermes.plugin import register
from toee_hermes.plugin.profiles import INTERNAL


class RecordingCtx:
    def __init__(self, profile: str | None = None) -> None:
        self.profile = profile
        self.tools: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Any]] = []

    def register_tool(self, *, name: str, toolset: str, schema: dict, handler: Any) -> None:
        self.tools.append(
            {"name": name, "toolset": toolset, "schema": schema, "handler": handler}
        )

    def register_hook(self, event: str, callback: Any) -> None:
        self.hooks.append((event, callback))


def _memory_upsert_handler(ctx: RecordingCtx) -> Any:
    return next(
        tool
        for tool in ctx.tools
        if tool["name"] == "toee_customer_memory__upsert_preference"
    )["handler"]


def test_unbound_register_binds_a_verified_memory_write_to_the_identity(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_DRIVER", "mock")
    ctx = RecordingCtx(profile=INTERNAL)
    identity = {
        "outcome": "verified_customer",
        "shopify_customer_id": "gid://shopify/Customer/2002",
    }

    register(ctx, identity=identity)

    out = json.loads(
        _memory_upsert_handler(ctx)(
            {"key": "contact_time_preference", "value": "after 6pm"}
        )
    )
    # The write bound to the verified Shopify id from context.identity (not the
    # model-supplied provisional carve-out), and the Internal profile stamps the
    # employee-confirmed source (RK-1).
    assert out["binding_key"] == "gid://shopify/Customer/2002"
    assert out["source"] == "employee_confirmed"


def test_unbound_register_binds_a_provisional_memory_write_to_the_3_part_key(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_DRIVER", "mock")
    ctx = RecordingCtx(profile=INTERNAL)
    identity = {"channel": "sms", "channel_identity": "+1 (416) 555-0175"}

    register(ctx, identity=identity)

    out = json.loads(
        _memory_upsert_handler(ctx)(
            {"key": "delivery_habit_note", "value": "loading dock"}
        )
    )
    # Aligned to the canonical 3-part provisional key (E.164-normalized), matching
    # the read key derived from the case's thread identity.
    assert out["binding_key"] == "provisional:sms:+14165550175"


def test_unbound_register_without_identity_is_unchanged(monkeypatch) -> None:
    # Backward-compat: the plugin entry point + eval/replay still call register(ctx)
    # with no identity; the context carries none and the tools still register.
    monkeypatch.setenv("INTEGRATION_DRIVER", "mock")
    ctx = RecordingCtx(profile=INTERNAL)

    register(ctx)

    assert any(
        t["name"] == "toee_customer_memory__upsert_preference" for t in ctx.tools
    )
