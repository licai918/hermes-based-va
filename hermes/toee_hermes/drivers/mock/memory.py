"""Mock handlers for ``toee_customer_memory`` (ports mock/memory.ts, ADR-0114).

Implements the v1 Customer Memory actions over the fixed four preference slots of
ADR-0111: open-ended keys are rejected rather than silently stored. Memory binds
to the verified ``shopify_customer_id`` from the Session Identity Snapshot
(``context.identity``, ADR-0043) or, when unverified, to a canonical provisional
channel key derived from context — fail-closed when no channel identity resolves,
never a shared bucket (:func:`resolve_customer_memory_binding`, ADR-0112, PRD
FR-5/S02). Reads honor an injected baseline so a scenario ``memory_preset``
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


def resolve_customer_memory_binding(
    context: "ToolExecutionContext", params: dict[str, Any]
) -> tuple[str, str]:
    """Resolve ``(binding_key, binding_kind)`` from context, fail-closed (S02, FR-5).

    ONE shared resolver for both the mock and Postgres datastore handlers — kept
    here since hermes-runtime already imports ``MEMORY_PREFERENCE_SLOTS`` from this
    module as the single source of truth for the slot enum. This is
    security-sensitive binding logic that must not drift between the two paths.

    A verified Session Identity Snapshot (``context.identity["outcome"] ==
    "verified_customer"``) binds to its Shopify customer id, kind ``"verified"``.
    Otherwise the caller's ingress-controlled channel identity
    (``context.identity["channel"]`` / ``["channel_identity"]``, S01) is
    canonicalized to ``provisional:{channel}:{E.164}`` (e.g.
    ``provisional:sms:+17786803250``), kind ``"provisional"`` — never a
    model-supplied param, so the model cannot bind or read another caller's memory
    by supplying a phone number as a tool argument (RK-3). A degenerate channel
    identity (missing, empty, or normalizing to a bare ``"+"``) is treated as no
    identity at all, not a shared bucket.

    ``channel_identity_id`` in ``params`` is honored only as a last resort on the
    ``internal_copilot`` profile (employee-confirmed corrections over the unbound
    workbench dispatch path, which carries no channel identity in context). Every
    other profile — including external — ignores it entirely.

    No resolvable identity at all raises a fail-closed ``policy_blocked``; the bare
    shared ``"provisional"`` key from pre-S02 (a cross-customer leak) is gone.
    """
    # Deferred imports: this module loads as part of ``drivers.mock``'s own
    # package init (which ``toee_hermes.plugin`` imports in turn), so importing
    # ``gateway``/``plugin.profiles`` at module scope here would re-enter that
    # partially-initialized package during a cold import and raise ImportError.
    from ...gateway.normalize import normalize_e164
    from ...plugin.profiles import INTERNAL

    identity = context.identity if isinstance(context.identity, dict) else {}

    if identity.get("outcome") == "verified_customer":
        shopify_customer_id = identity.get("shopify_customer_id")
        if isinstance(shopify_customer_id, str) and shopify_customer_id:
            return shopify_customer_id, "verified"

    channel = identity.get("channel")
    channel_identity = identity.get("channel_identity")
    if isinstance(channel, str) and channel and isinstance(channel_identity, str):
        normalized = normalize_e164(channel_identity)
        if normalized != "+":
            return f"provisional:{channel}:{normalized}", "provisional"

    if context.profile == INTERNAL:
        channel_identity_id = _read_string(
            params, "channel_identity_id", "channelIdentityId"
        )
        if channel_identity_id is not None:
            return f"provisional:{channel_identity_id}", "provisional"

    raise ToolDriverError(
        "policy_blocked",
        "Customer Memory requires a resolvable channel identity; the turn has "
        "none (fail-closed, ADR-0112 / PRD FR-5).",
    )


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
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
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
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
        slots_for(binding_key).pop(slot, None)
        return {"binding_key": binding_key, "slot": slot, "cleared": True}

    def get_preferences(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Returns the current preference slots for the active binding, honoring any
        # injected baseline (scenario 25).
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
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
