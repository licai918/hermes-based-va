"""Governed failure classification for Domain Adapter Tool execution.

Ports `errors.ts`. Dispatch-level classes (`unknown_tool`, `unknown_action`,
`policy_blocked`) sit alongside the runtime driver classes from ADR-0136.
`not_found`/`conflict` are datastore resource-state denials (a missing or
contended row), which the workbench BFF maps to 404/409. `unauthenticated` is a
rejected credential on the pre-auth login verification (ADR-0144), which the BFF
maps to 401. `unexpected_error` covers driver throws the driver did not classify
itself.
"""

from __future__ import annotations

from typing import Literal

ToolErrorClass = Literal[
    "unknown_tool",
    "unknown_action",
    "policy_blocked",
    "not_found",
    "conflict",
    "unauthenticated",
    "auth_expired",
    "vendor_timeout",
    "composio_api_error",
    "configuration_missing",
    "unexpected_error",
]


class ToolDriverError(Exception):
    """Raised by drivers to signal a governed Tool Unavailable Response.

    The raw ``message`` is for logs/audit only and must never reach a
    customer-facing reply (ADR-0020, ADR-0136).
    """

    def __init__(self, error_class: ToolErrorClass, message: str) -> None:
        super().__init__(message)
        self.error_class: ToolErrorClass = error_class
