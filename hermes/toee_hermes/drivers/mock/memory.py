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

# Framework-derived write sources (PRD FR-3, RK-1). ``customer_explicit`` and
# ``employee_confirmed`` are set by :func:`resolve_memory_write_source`, never by
# a model-supplied tool param. ``merged_provisional`` is reserved for the async
# provisional-to-verified merge path (S10) and is not produced by either write
# handler in this module -- it is listed here so the enum never needs a second
# change when that path lands.
MEMORY_SOURCE_VALUES: tuple[str, ...] = (
    "customer_explicit",
    "employee_confirmed",
    "merged_provisional",
)

# ADR-0111 slots hold a short preference note (e.g. "after 2pm"), not free text;
# PRD FR-3 caps the stored value so a write can't smuggle an essay into a slot.
MEMORY_VALUE_MAX_LENGTH = 200


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


def _require_value(params: dict[str, Any]) -> str:
    """Resolve and validate ``value``: a string, capped at 200 chars (PRD FR-3)."""
    value = params.get("value")
    if not isinstance(value, str):
        raise ToolDriverError(
            "unexpected_error", "upsert_preference requires a string value."
        )
    if len(value) > MEMORY_VALUE_MAX_LENGTH:
        raise ToolDriverError(
            "unexpected_error",
            "Customer Memory rejects a value longer than "
            f"{MEMORY_VALUE_MAX_LENGTH} characters.",
        )
    return value


def _read_evidence(params: dict[str, Any]) -> str | None:
    """Resolve the optional ``evidence`` param (verbatim customer phrase)."""
    evidence = params.get("evidence")
    if evidence is None:
        return None
    if not isinstance(evidence, str):
        raise ToolDriverError(
            "unexpected_error",
            "upsert_preference evidence must be a string when provided.",
        )
    return evidence


def binding_key_from_identity(identity: Any) -> tuple[str, str] | None:
    """Pure identity dict -> ``(binding_key, binding_kind)`` core, or ``None``.

    The security-sensitive derivation shared by BOTH the governed WRITE path
    (:func:`resolve_customer_memory_binding`) and the turn-time READ injection
    (openrouter/copilot, S07/S08): reads and writes MUST compute a byte-identical
    key for a given identity or the memory round-trip silently returns nothing.

    A verified Session Identity Snapshot (``identity["outcome"] ==
    "verified_customer"``) binds to its Shopify customer id, kind ``"verified"``.
    Otherwise the caller's ingress-controlled channel identity
    (``identity["channel"]`` / ``["channel_identity"]``, S01) is canonicalized to
    ``provisional:{channel}:{E.164}`` (e.g. ``provisional:sms:+17786803250``), kind
    ``"provisional"`` — never a model-supplied param (RK-3). A degenerate channel
    identity (missing, empty, or normalizing to a bare ``"+"``) yields ``None``, not
    a shared bucket.

    Returns ``None`` when nothing resolves — the caller decides the fail-closed
    policy: the write path raises ``policy_blocked``; the read path injects nothing.
    """
    # Deferred import: this module loads as part of ``drivers.mock``'s own package
    # init (which ``toee_hermes.plugin`` imports in turn), so importing ``gateway``
    # at module scope here would re-enter that partially-initialized package during
    # a cold import and raise ImportError.
    from ...gateway.normalize import normalize_e164

    if not isinstance(identity, dict):
        return None

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

    return None


def resolve_customer_memory_binding(
    context: "ToolExecutionContext", params: dict[str, Any]
) -> tuple[str, str]:
    """Resolve ``(binding_key, binding_kind)`` for a WRITE, fail-closed (S02, FR-5).

    Thin wrapper over :func:`binding_key_from_identity` (the shared pure core) that
    adds the two write-only concerns: the ``internal_copilot`` param carve-out and
    the fail-closed ``policy_blocked`` raise. Kept here since hermes-runtime already
    imports ``MEMORY_PREFERENCE_SLOTS`` from this module as the single source of
    truth for the slot enum.

    ``channel_identity_id`` in ``params`` is honored only as a last resort on the
    ``internal_copilot`` profile (employee-confirmed corrections over the unbound
    workbench dispatch path, which carries no channel identity in context). Every
    other profile — including external — ignores it entirely.

    No resolvable identity at all raises a fail-closed ``policy_blocked``; the bare
    shared ``"provisional"`` key from pre-S02 (a cross-customer leak) is gone.
    """
    # Deferred import: same partially-initialized-package hazard as the core above.
    from ...plugin.profiles import INTERNAL

    resolved = binding_key_from_identity(context.identity)
    if resolved is not None:
        return resolved

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


def resolve_memory_write_source(context: "ToolExecutionContext") -> str:
    """Framework-derived ``source`` for a preference write (RK-1, PRD FR-3).

    ONE shared resolver for both the mock and Postgres datastore handlers, same
    reasoning as :func:`resolve_customer_memory_binding`: this is
    security-sensitive governance logic that must not drift between the two.

    Never taken from the model-supplied tool params -- the model cannot forge
    ``customer_explicit`` for an inferred write. The External Customer Service
    Profile always writes ``customer_explicit``; the Internal Copilot Profile
    always writes ``employee_confirmed``. ``merged_provisional`` is set only by
    the merge path (S10), never by this resolver. Any other profile is
    fail-closed -- ``toee_customer_memory`` is not allowlisted outside these two
    today (ADR-0034/35), so this is defense in depth, not a reachable path.
    """
    # Deferred import: same partially-initialized-package hazard documented on
    # resolve_customer_memory_binding above.
    from ...plugin.profiles import EXTERNAL, INTERNAL

    if context.profile == EXTERNAL:
        return "customer_explicit"
    if context.profile == INTERNAL:
        return "employee_confirmed"
    raise ToolDriverError(
        "policy_blocked",
        f'Customer Memory writes are not permitted for profile "{context.profile}".',
    )


def create_memory_mock_handlers(
    data: MemoryMockData = memory_baseline_data,
    *,
    evidence_store: dict[str, dict[str, str]] | None = None,
) -> MockHandlerRegistry:
    """Build ``toee_customer_memory`` handlers backed by a per-binding store.

    A fresh store is created per factory call and closed over by the handlers, so
    in-memory writes persist across calls within one handler-set instance while
    staying isolated per identity binding. Each binding is lazily seeded from the
    injected baseline so a scenario ``memory_preset`` is honored on first read.

    ``evidence_store``, when supplied, is mutated in place with each write's
    ``evidence`` (``binding_key -> {slot: evidence}``) -- mirrors the datastore
    handler's ``evidence`` column so a caller (a test, mainly) can prove evidence
    is actually persisted and retrievable, not just echoed back on the same call
    (PRD FR-3). Not exposed through ``get_preferences``, matching how ``source``
    already isn't -- both are write-time governance/audit metadata, not part of
    the live preference value re-injected into the prompt every turn (RK-2).
    """
    store: dict[str, dict[str, str]] = {}
    evidence: dict[str, dict[str, str]] = (
        {} if evidence_store is None else evidence_store
    )

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
        value = _require_value(params)
        write_evidence = _read_evidence(params)
        # RK-1: source is framework-derived from context.profile, never the
        # model-supplied params — any "source" the caller passed is ignored.
        source = resolve_memory_write_source(context)
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
        slots_for(binding_key)[slot] = value
        if write_evidence is not None:
            evidence.setdefault(binding_key, {})[slot] = write_evidence
        return {
            "binding_key": binding_key,
            "slot": slot,
            "value": value,
            "source": source,
            "evidence": write_evidence,
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
