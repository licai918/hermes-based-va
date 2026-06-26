"""Tests for the async Textline turn-binding Tool Gate (ADR-0107, ADR-0066).

The async agent turn runs with the inbound turn's loaded session context. An
outbound ``toee_textline_reply.send_message`` must target the bound conversation
(and SMS Session) of that turn; a send aimed at a different conversation — or one
that omits the binding — is a governed ``policy_blocked`` failure so model output
can never redirect a reply to another thread or number.
"""

from __future__ import annotations

from toee_hermes.execute import ToolRequest
from toee_hermes.gates import create_turn_binding_gate
from toee_hermes.tool_gate import ToolExecutionContext

EXTERNAL = "customer_service_external"


def _bound_context() -> ToolExecutionContext:
    return ToolExecutionContext(
        profile=EXTERNAL, conversation_id="conv-1", sms_session_id="sess-1"
    )


def test_tool_execution_context_carries_optional_turn_binding() -> None:
    context = ToolExecutionContext(
        profile=EXTERNAL,
        conversation_id="conv-1",
        sms_session_id="sess-1",
    )
    assert context.conversation_id == "conv-1"
    assert context.sms_session_id == "sess-1"


def test_tool_execution_context_turn_binding_defaults_to_none() -> None:
    context = ToolExecutionContext(profile=EXTERNAL)
    assert context.conversation_id is None
    assert context.sms_session_id is None


def test_allows_reply_that_targets_the_bound_conversation() -> None:
    gate = create_turn_binding_gate()
    decision = gate(
        ToolRequest(
            tool="toee_textline_reply",
            action="send_message",
            params={"conversation_id": "conv-1", "body": "On its way."},
        ),
        _bound_context(),
    )
    assert decision.allow is True


def test_blocks_reply_that_targets_a_different_conversation() -> None:
    gate = create_turn_binding_gate()
    decision = gate(
        ToolRequest(
            tool="toee_textline_reply",
            action="send_message",
            params={"conversation_id": "conv-OTHER", "body": "leak"},
        ),
        _bound_context(),
    )
    assert decision.allow is False
    assert decision.error_class == "policy_blocked"


def test_blocks_reply_that_omits_the_conversation_when_bound() -> None:
    # A send that does not name the bound conversation cannot be proven to target
    # the inbound turn's thread, so it is denied (ADR-0107).
    gate = create_turn_binding_gate()
    decision = gate(
        ToolRequest(
            tool="toee_textline_reply",
            action="send_message",
            params={"body": "where to?"},
        ),
        _bound_context(),
    )
    assert decision.allow is False
    assert decision.error_class == "policy_blocked"


def test_allows_non_reply_tools_under_a_turn_binding() -> None:
    gate = create_turn_binding_gate()
    decision = gate(
        ToolRequest(tool="toee_shopify_read", action="get_order"),
        _bound_context(),
    )
    assert decision.allow is True


def test_gate_is_inert_without_a_turn_binding() -> None:
    # Eval and Copilot paths carry no async turn binding; the gate must not block
    # reply sends there (it governs only the bound async gateway turn).
    gate = create_turn_binding_gate()
    decision = gate(
        ToolRequest(
            tool="toee_textline_reply",
            action="send_message",
            params={"conversation_id": "conv-anything", "body": "ok"},
        ),
        ToolExecutionContext(profile=EXTERNAL),
    )
    assert decision.allow is True
