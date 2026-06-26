"""Datastore handlers for ``toee_customer_memory`` (ADR-0110-0114).

Persists the fixed four preference slots (ADR-0111) to ``customer_memory_slot``,
bound to the verified Shopify customer id (Session Identity Snapshot, ADR-0043)
or a provisional channel key (ADR-0112). Open-ended keys are rejected, never
silently stored. The four-slot enum is imported from the plugin so the datastore
and mock paths share one source of truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from toee_hermes.drivers.mock.memory import MEMORY_PREFERENCE_SLOTS
from toee_hermes.errors import ToolDriverError

from ._common import new_id, read_string

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

_DEFAULT_SOURCE = "unspecified"


def _require_slot(params: dict[str, Any]) -> str:
    requested = params.get("key")
    if requested is None:
        requested = params.get("slot")
    if not (isinstance(requested, str) and requested in MEMORY_PREFERENCE_SLOTS):
        raise ToolDriverError(
            "unexpected_error",
            f'Customer Memory rejects open-ended preference key "{requested}"; '
            "only the four v1 slots are allowed (ADR-0111).",
        )
    return requested


def _resolve_binding(
    context: "ToolExecutionContext", params: dict[str, Any]
) -> tuple[str, str]:
    """Return ``(binding_key, binding_kind)``: verified Shopify id else provisional."""
    identity = context.identity
    if isinstance(identity, dict) and identity.get("outcome") == "verified_customer":
        shopify_customer_id = identity.get("shopify_customer_id")
        if isinstance(shopify_customer_id, str) and shopify_customer_id:
            return shopify_customer_id, "verified"
    channel_identity_id = read_string(params, "channel_identity_id", "channelIdentityId")
    if channel_identity_id is not None:
        return f"provisional:{channel_identity_id}", "provisional"
    return "provisional", "provisional"


def _upsert_preference(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    slot = _require_slot(params)
    value = params.get("value")
    if not isinstance(value, str):
        raise ToolDriverError(
            "unexpected_error", "upsert_preference requires a string value."
        )
    raw_source = params.get("source")
    source = raw_source if isinstance(raw_source, str) and raw_source else _DEFAULT_SOURCE
    binding_key, binding_kind = _resolve_binding(context, params)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_slot
                (id, binding_key, binding_kind, slot_name, slot_value, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (binding_key, slot_name) DO UPDATE SET
                slot_value = EXCLUDED.slot_value,
                source = EXCLUDED.source,
                binding_kind = EXCLUDED.binding_kind,
                updated_at = now(),
                last_interaction_at = now()
            """,
            (new_id("mem"), binding_key, binding_kind, slot, value, source),
        )
    return {
        "binding_key": binding_key,
        "slot": slot,
        "value": value,
        "source": source,
        "stored": True,
    }


def _clear_preference(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    slot = _require_slot(params)
    binding_key, _ = _resolve_binding(context, params)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM customer_memory_slot WHERE binding_key = %s AND slot_name = %s",
            (binding_key, slot),
        )
    return {"binding_key": binding_key, "slot": slot, "cleared": True}


def _get_preferences(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    binding_key, _ = _resolve_binding(context, params)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_name, slot_value FROM customer_memory_slot WHERE binding_key = %s",
            (binding_key,),
        )
        rows = cur.fetchall()
    return {
        "binding_key": binding_key,
        "preferences": {name: value for name, value in rows},
    }


def memory_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the Customer Memory datastore tool."""
    return {
        "toee_customer_memory": {
            "upsert_preference": _upsert_preference,
            "clear_preference": _clear_preference,
            "get_preferences": _get_preferences,
        }
    }
