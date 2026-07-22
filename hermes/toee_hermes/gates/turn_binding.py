"""Async SMS turn-binding Tool Gate (ADR-0107, ADR-0066).

The async agent turn runs with the inbound turn's loaded session context, which
carries the bound ``conversation_id`` (ADR-0107). This gate enforces that an
outbound ``toee_sms_reply`` targets exactly that conversation: a send naming a
different conversation — or omitting it — is denied with ``policy_blocked`` so model
output can never redirect a reply to another thread (ADR-0066 rejects letting reply
tools target a model-supplied destination).

The gate is scoped to the bound async path: when the context carries no turn
binding (eval and Copilot paths), it is inert and allows the send. Outbound binding
to the conversation is the authorization; the route already verified the inbound
binding before running the turn.
"""

from __future__ import annotations

from typing import Any

from ..tool_gate import GateDecision, ToolExecutionContext, ToolGate

SMS_REPLY_TOOL = "toee_sms_reply"


def _target_conversation(params: dict[str, Any]) -> Any:
    return params.get("conversation_id") or params.get("conversationId")


def create_turn_binding_gate() -> ToolGate:
    """Build the gate that binds outbound replies to the loaded turn's conversation."""

    def gate(request: Any, context: ToolExecutionContext) -> GateDecision:
        if request.tool != SMS_REPLY_TOOL:
            return GateDecision(allow=True)

        bound = context.conversation_id
        if not bound:
            # No async turn binding in context: this gate does not apply here.
            return GateDecision(allow=True)

        if _target_conversation(request.params) != bound:
            return GateDecision(
                allow=False,
                error_class="policy_blocked",
                message=(
                    "Outbound reply must target the inbound turn's conversation."
                ),
            )
        return GateDecision(allow=True)

    return gate
