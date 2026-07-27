"""Tool Gate primitives (ports tool-gate.ts).

A Tool Gate runs inside dispatch before the driver is invoked. It is not a
separate Hermes core module (ADR-0033); it is the hook point Toee Tire policy
checks plug into.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional

from .errors import ToolErrorClass

if TYPE_CHECKING:
    from .execute import ToolRequest


# The deterministic admin-BFF surface (ADR-0141 ``POST /v1/tools:dispatch``).
# Set ONLY by ``hermes_runtime.tool_dispatch_app``, which reaches it behind the
# shared bearer -- never read from a param and never from the runtime kwargs the
# agent loop hands a tool handler, so nothing inside a turn can claim it.
TOOLS_DISPATCH_ROUTE = "tools_dispatch"


@dataclass(frozen=True)
class ToolExecutionContext:
    """Runtime context a Tool Gate evaluates against (ADR-0033, ADR-0136)."""

    profile: str
    identity: Optional[Any] = None
    user_id: Optional[str] = None
    connected_account_id: Optional[str] = None
    # Which SURFACE reached dispatch, not who the actor is. `profile` says which
    # home is running; this says whether the call came from a deterministic
    # request or from inside an agent turn -- two things that share the
    # internal_copilot profile and are otherwise indistinguishable. Framework-set
    # at the construction site (a literal, never a kwarg); default None means
    # "not the deterministic dispatch surface", which is the fail-safe reading for
    # every other caller (agent turns, eval, ingress, background jobs).
    dispatch_route: Optional[str] = None
    # Async SMS turn binding (ADR-0107): the conversation / SMS Session the
    # loaded inbound turn belongs to. Set by the gateway turn runner so an outbound
    # reply can be enforced to target this thread only; None outside that path.
    conversation_id: Optional[str] = None
    sms_session_id: Optional[str] = None


@dataclass(frozen=True)
class GateDecision:
    """Allow, or deny with a governed error class + log message."""

    allow: bool
    error_class: Optional[ToolErrorClass] = None
    message: Optional[str] = None


ToolGate = Callable[["ToolRequest", ToolExecutionContext], GateDecision]


def allow_all_gate(request: "ToolRequest", context: ToolExecutionContext) -> GateDecision:
    """Default gate used when no policy checks are wired (mock-first scaffold)."""
    return GateDecision(allow=True)
