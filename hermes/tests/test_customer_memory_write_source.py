"""Unit tests for the shared Customer Memory write-source resolver (S03, PRD FR-3).

Exercises :func:`resolve_memory_write_source` directly (context only, no DB, no
driver) -- the ONE source-derivation both the mock and Postgres datastore
handlers import, so ``source`` can never be forged via a model-supplied tool
param (RK-1) on either path. Mirrors ``test_customer_memory_binding.py``'s
treatment of the shared binding resolver.
"""

import pytest

from toee_hermes.drivers.mock.memory import (
    MEMORY_SOURCE_VALUES,
    resolve_memory_write_source,
)
from toee_hermes.errors import ToolDriverError
from toee_hermes.tool_gate import ToolExecutionContext

EXTERNAL = "customer_service_external"
INTERNAL = "internal_copilot"
SUPERVISOR = "supervisor_admin"


def _ctx(profile: str) -> ToolExecutionContext:
    return ToolExecutionContext(profile=profile)


def test_external_profile_resolves_customer_explicit() -> None:
    assert resolve_memory_write_source(_ctx(EXTERNAL)) == "customer_explicit"


def test_internal_copilot_resolves_employee_confirmed() -> None:
    assert resolve_memory_write_source(_ctx(INTERNAL)) == "employee_confirmed"


def test_accepted_enum_includes_merged_provisional_for_future_merge_path() -> None:
    # S10 (merge, not this slice) is the only writer of merged_provisional; the
    # enum must already accept it so that path never needs a second change here.
    assert MEMORY_SOURCE_VALUES == (
        "customer_explicit",
        "employee_confirmed",
        "merged_provisional",
    )


def test_every_resolved_source_is_in_the_accepted_enum() -> None:
    for profile in (EXTERNAL, INTERNAL):
        assert resolve_memory_write_source(_ctx(profile)) in MEMORY_SOURCE_VALUES


def test_unsupported_profile_is_policy_blocked() -> None:
    # toee_customer_memory isn't allowlisted for supervisor_admin today, but the
    # resolver itself is fail-closed for defense in depth (same posture as
    # resolve_customer_memory_binding).
    with pytest.raises(ToolDriverError) as exc_info:
        resolve_memory_write_source(_ctx(SUPERVISOR))
    assert exc_info.value.error_class == "policy_blocked"
