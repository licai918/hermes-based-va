"""Mock handlers for ``toee_customer_memory`` (ports mock/memory.ts, ADR-0114).

Implements the v1 Customer Memory actions over the fixed four preference slots of
ADR-0111: open-ended keys are rejected rather than silently stored. Memory binds
to the verified ``shopify_customer_id`` from the Session Identity Snapshot
(``context.identity``, ADR-0043) or, when unverified, to a provisional channel
binding (ADR-0112). Reads honor an injected baseline so a scenario ``memory_preset``
is reflected on first read (ADR-0113 lightweight injection). Writes are
explicit-only: this driver never infers or fabricates a preference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...errors import ToolDriverError
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext

# The four v1 Customer Memory preference slots (ADR-0111). Only these slots may be
# written, cleared, or read; anything else is a governed rejection.
MEMORY_PREFERENCE_SLOTS: tuple[str, ...] = (
    "contact_time_preference",
    "channel_preference",
    "delivery_habit_note",
    "communication_style_note",
)


@dataclass(frozen=True)
class MemoryMockData:
    # Slot map injected for the active identity binding before a turn runs — the
    # mock equivalent of ADR-0113 lightweight injection (a scenario
    # ``memory_preset``). Default empty: nothing is remembered until an explicit
    # write happens.
    preferences: dict[str, str] = field(default_factory=dict)


# Baseline fixtures: empty, so nothing is remembered without an explicit write.
memory_baseline_data = MemoryMockData()


def _is_preference_slot(value: Any) -> bool:
    return isinstance(value, str) and value in MEMORY_PREFERENCE_SLOTS


def _require_slot(params: dict[str, Any]) -> str:
    """Resolve the target slot from ``key`` (the v1 param) or its ``slot`` alias.

    Open-ended preference keys are rejected per ADR-0111 rather than silently
    stored, so an inferred or non-v1 write never lands in memory.
    """
    requested = params.get("key")
    if requested is None:
        requested = params.get("slot")
    if not _is_preference_slot(requested):
        raise ToolDriverError(
            "unexpected_error",
            (
                f'Customer Memory rejects open-ended preference key "{requested}"; '
                "only the four v1 slots are allowed (ADR-0111)."
            ),
        )
    return requested


def _read_string(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _resolve_binding_key(
    context: "ToolExecutionContext", params: dict[str, Any]
) -> str:
    """Bind to the verified ``shopify_customer_id``, else a provisional channel key.

    A verified Session Identity Snapshot binds memory to its Shopify customer id;
    otherwise the binding is provisional and keyed by the channel identity supplied
    in ``params`` (ADR-0112). Ambiguous matches never merge in v1, so they are not
    split further here. With no channel identity, a single ``provisional`` bucket
    is used.
    """
    identity = context.identity
    if isinstance(identity, dict) and identity.get("outcome") == "verified_customer":
        shopify_customer_id = identity.get("shopify_customer_id")
        if isinstance(shopify_customer_id, str) and shopify_customer_id:
            return shopify_customer_id
    channel_identity_id = _read_string(
        params, "channel_identity_id", "channelIdentityId"
    )
    if channel_identity_id is not None:
        return f"provisional:{channel_identity_id}"
    return "provisional"


def create_memory_mock_handlers(
    data: MemoryMockData = memory_baseline_data,
) -> MockHandlerRegistry:
    """Build ``toee_customer_memory`` handlers backed by a per-binding store.

    A fresh store is created per factory call and closed over by the handlers, so
    in-memory writes persist across calls within one handler-set instance while
    staying isolated per identity binding. Each binding is lazily seeded from the
    injected baseline so a scenario ``memory_preset`` is honored on first read.
    """
    store: dict[str, dict[str, str]] = {}

    def slots_for(binding_key: str) -> dict[str, str]:
        slots = store.get(binding_key)
        if slots is None:
            slots = dict(data.preferences)
            store[binding_key] = slots
        return slots

    def upsert_preference(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Records one explicit preference slot and echoes the stored value
        # (scenario 24). The Tool Gate — not this driver — enforces that the write
        # came from explicit customer language (ADR-0114).
        slot = _require_slot(params)
        value = params.get("value")
        if not isinstance(value, str):
            raise ToolDriverError(
                "unexpected_error", "upsert_preference requires a string value."
            )
        source = params.get("source")
        if not isinstance(source, str):
            source = None
        binding_key = _resolve_binding_key(context, params)
        slots_for(binding_key)[slot] = value
        return {
            "binding_key": binding_key,
            "slot": slot,
            "value": value,
            "source": source,
            "stored": True,
        }

    def clear_preference(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Clears one preference slot and acknowledges the removal.
        slot = _require_slot(params)
        binding_key = _resolve_binding_key(context, params)
        slots_for(binding_key).pop(slot, None)
        return {"binding_key": binding_key, "slot": slot, "cleared": True}

    def get_preferences(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Returns the current preference slots for the active binding, honoring any
        # injected baseline (scenario 25).
        binding_key = _resolve_binding_key(context, params)
        return {
            "binding_key": binding_key,
            "preferences": dict(slots_for(binding_key)),
        }

    return {
        "toee_customer_memory": {
            "upsert_preference": upsert_preference,
            "clear_preference": clear_preference,
            "get_preferences": get_preferences,
        }
    }
