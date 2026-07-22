"""Binding-aware registration for the async SMS turn (ADR-0107, ADR-0139).

``register_turn(ctx, conversation_id=...)`` is the gateway-embedding entry point:
it registers the profile's allowlisted tools exactly like ``register`` but binds
the loaded turn's ``conversation_id`` into every governed dispatch and wires the
turn-binding gate, so a scripted/model ``toee_sms_reply.send_message`` can
only target the inbound turn's conversation (ADR-0066). The default ``register``
(eval/replay + Copilot paths) stays unbound and unconstrained.

These run the real governed dispatch (:func:`execute_tool`) over the real
:class:`MockDriver` through a faithful ``RecordingCtx`` — no fabricated handler.
"""

from __future__ import annotations

import json
from typing import Any

from toee_hermes.plugin import register, register_turn
from toee_hermes.plugin.profiles import EXTERNAL


class RecordingCtx:
    """Minimal faithful stand-in for the Hermes plugin registration context."""

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


def _reply_handler(ctx: RecordingCtx) -> Any:
    entry = next(
        tool
        for tool in ctx.tools
        if tool["name"] == "toee_sms_reply__send_message"
    )
    return entry["handler"]


def test_register_turn_admits_a_reply_that_targets_the_bound_conversation() -> None:
    ctx = RecordingCtx(profile=EXTERNAL)
    register_turn(ctx, conversation_id="conv-A")

    out = json.loads(
        _reply_handler(ctx)({"conversation_id": "conv-A", "body": "On its way"})
    )

    assert out.get("conversation_id") == "conv-A"
    assert out.get("body") == "On its way"
    assert "error_class" not in out


def test_register_turn_blocks_a_reply_to_a_different_conversation() -> None:
    ctx = RecordingCtx(profile=EXTERNAL)
    register_turn(ctx, conversation_id="conv-A")

    out = json.loads(
        _reply_handler(ctx)({"conversation_id": "conv-B", "body": "wrong thread"})
    )

    assert out["error_class"] == "policy_blocked"


def test_register_turn_blocks_a_reply_that_omits_the_conversation() -> None:
    ctx = RecordingCtx(profile=EXTERNAL)
    register_turn(ctx, conversation_id="conv-A")

    out = json.loads(_reply_handler(ctx)({"body": "no thread named"}))

    assert out["error_class"] == "policy_blocked"


def test_unbound_register_leaves_the_reply_tool_unconstrained() -> None:
    # eval/replay + Copilot paths carry no turn binding, so wiring the binding gate
    # into the default register must not constrain which conversation a send targets.
    ctx = RecordingCtx(profile=EXTERNAL)
    register(ctx)

    out = json.loads(
        _reply_handler(ctx)({"conversation_id": "anything", "body": "ok"})
    )

    assert out.get("conversation_id") == "anything"
    assert "error_class" not in out
