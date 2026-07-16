"""Unit tests for the shared Customer Memory binding resolver (S02, PRD FR-5).

Exercises :func:`resolve_customer_memory_binding` directly (context + params, no
DB, no driver) — the ONE binding-key derivation both the mock and Postgres
datastore handlers import, so it must never drift between the two paths.

Covers correctness rules R1 (verified vs provisional canonical key), R6
(fail-closed on no/degenerate channel identity; a model-supplied phone param
cannot move the binding on the external profile), and R3 (the internal_copilot
``channel_identity_id`` param carve-out is removed: binding is context-only on
every profile, PRD FR-5).
"""

import pytest

from toee_hermes.drivers.mock.memory import (
    binding_key_from_identity,
    resolve_customer_memory_binding,
)
from toee_hermes.errors import ToolDriverError
from toee_hermes.tool_gate import ToolExecutionContext

EXTERNAL = "customer_service_external"
INTERNAL = "internal_copilot"


def _ctx(profile: str = EXTERNAL, identity=None) -> ToolExecutionContext:
    return ToolExecutionContext(profile=profile, identity=identity)


# --- R1: verified vs provisional -------------------------------------------


def test_verified_outcome_binds_to_shopify_customer_id() -> None:
    identity = {
        "outcome": "verified_customer",
        "shopify_customer_id": "gid://shopify/Customer/1001",
        # S01 always merges the channel identity too, even for verified callers.
        "channel": "sms",
        "channel_identity": "+17786803250",
    }
    key, kind = resolve_customer_memory_binding(_ctx(identity=identity), {})
    assert key == "gid://shopify/Customer/1001"
    assert kind == "verified"


def test_provisional_binding_uses_canonical_form_from_context() -> None:
    identity = {"channel": "sms", "channel_identity": "+17786803250"}
    key, kind = resolve_customer_memory_binding(_ctx(identity=identity), {})
    assert key == "provisional:sms:+17786803250"
    assert kind == "provisional"


def test_provisional_key_normalizes_a_non_canonical_channel_identity() -> None:
    identity = {"channel": "sms", "channel_identity": "(778) 680-3250"}
    key, _kind = resolve_customer_memory_binding(_ctx(identity=identity), {})
    assert key == "provisional:sms:+17786803250"


def test_unmatched_caller_outcome_still_binds_provisionally_from_context() -> None:
    # A resolved-but-unmatched Session Identity Snapshot still carries an
    # "outcome" key (unmatched_caller) alongside the channel identity (S01) —
    # only "verified_customer" takes the verified branch.
    identity = {
        "outcome": "unmatched_caller",
        "channel": "sms",
        "channel_identity": "+17786803250",
    }
    key, kind = resolve_customer_memory_binding(_ctx(identity=identity), {})
    assert key == "provisional:sms:+17786803250"
    assert kind == "provisional"


# --- R6: fail-closed ---------------------------------------------------------


def test_no_identity_at_all_is_policy_blocked() -> None:
    with pytest.raises(ToolDriverError) as exc_info:
        resolve_customer_memory_binding(_ctx(identity=None), {})
    assert exc_info.value.error_class == "policy_blocked"


def test_empty_channel_identity_is_policy_blocked_not_bare_provisional() -> None:
    identity = {"channel": "sms", "channel_identity": ""}
    with pytest.raises(ToolDriverError) as exc_info:
        resolve_customer_memory_binding(_ctx(identity=identity), {})
    assert exc_info.value.error_class == "policy_blocked"


def test_channel_identity_normalizing_to_bare_plus_is_policy_blocked() -> None:
    # normalize_e164("no digits here") == "+" — degenerate, never a resolvable key.
    identity = {"channel": "sms", "channel_identity": "no digits here"}
    with pytest.raises(ToolDriverError) as exc_info:
        resolve_customer_memory_binding(_ctx(identity=identity), {})
    assert exc_info.value.error_class == "policy_blocked"


def test_missing_channel_identity_key_is_policy_blocked() -> None:
    identity = {"channel": "sms"}
    with pytest.raises(ToolDriverError) as exc_info:
        resolve_customer_memory_binding(_ctx(identity=identity), {})
    assert exc_info.value.error_class == "policy_blocked"


def test_external_profile_ignores_model_supplied_channel_identity_id_param() -> None:
    # A model-supplied phone param must never move the binding on the external
    # profile — context is the only source. No context identity => still blocked.
    params = {"channel_identity_id": "+19998887777"}
    with pytest.raises(ToolDriverError) as exc_info:
        resolve_customer_memory_binding(_ctx(EXTERNAL, identity=None), params)
    assert exc_info.value.error_class == "policy_blocked"


# --- internal_copilot: channel_identity_id carve-out removed (R3, FR-5) -----


def test_internal_copilot_ignores_model_supplied_channel_identity_id_param() -> None:
    # R3: the carve-out is removed -- a model-supplied channel_identity_id no
    # longer binds on internal_copilot either. No context identity => policy_blocked,
    # never the old bound provisional:{param} key (mirrors the external-profile
    # case above; every profile is now context-only).
    params = {"channel_identity_id": "case:12345"}
    with pytest.raises(ToolDriverError) as exc_info:
        resolve_customer_memory_binding(_ctx(INTERNAL, identity=None), params)
    assert exc_info.value.error_class == "policy_blocked"


def test_internal_copilot_prefers_context_over_param_when_both_present() -> None:
    identity = {"channel": "sms", "channel_identity": "+17786803250"}
    params = {"channel_identity_id": "employee-typed-other"}
    key, _kind = resolve_customer_memory_binding(
        _ctx(INTERNAL, identity=identity), params
    )
    assert key == "provisional:sms:+17786803250"


def test_internal_copilot_without_param_or_context_is_policy_blocked() -> None:
    with pytest.raises(ToolDriverError) as exc_info:
        resolve_customer_memory_binding(_ctx(INTERNAL, identity=None), {})
    assert exc_info.value.error_class == "policy_blocked"


# --- binding_key_from_identity: the pure core shared with the turn-time READ ---
# resolve_customer_memory_binding is the WRITE-path wrapper (adds the fail-closed
# raise); binding_key_from_identity is the pure identity -> (key, kind) core the
# S07/S08 turn-time reader calls, so the READ key is byte-identical to the stored
# key. Read fail-closed = None, never a raise.


def test_binding_key_from_identity_verified_returns_shopify_id() -> None:
    identity = {
        "outcome": "verified_customer",
        "shopify_customer_id": "gid://shopify/Customer/1001",
        "channel": "sms",
        "channel_identity": "+17786803250",
    }
    assert binding_key_from_identity(identity) == (
        "gid://shopify/Customer/1001",
        "verified",
    )


def test_binding_key_from_identity_provisional_returns_canonical_key() -> None:
    identity = {"channel": "sms", "channel_identity": "(778) 680-3250"}
    assert binding_key_from_identity(identity) == (
        "provisional:sms:+17786803250",
        "provisional",
    )


def test_binding_key_from_identity_returns_none_when_unresolvable() -> None:
    # None (not a raise): the turn-time reader injects nothing; only the write
    # wrapper turns a None core into a policy_blocked ToolDriverError.
    assert binding_key_from_identity({}) is None
    assert binding_key_from_identity({"channel": "sms", "channel_identity": ""}) is None
    assert binding_key_from_identity({"channel": "sms"}) is None
    assert binding_key_from_identity(None) is None
