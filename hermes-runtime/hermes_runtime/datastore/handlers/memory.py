"""Datastore handlers for ``toee_customer_memory`` (ADR-0110-0114).

Persists the fixed four preference slots (ADR-0111) to ``customer_memory_slot``,
bound to the verified Shopify customer id (Session Identity Snapshot, ADR-0043)
or a canonical provisional channel key derived from context, fail-closed when no
channel identity resolves (:func:`resolve_customer_memory_binding`, ADR-0112, PRD
FR-5/S02). Open-ended keys are rejected, never silently stored, and a value over
``MEMORY_VALUE_MAX_LENGTH`` chars is rejected the same way (PRD FR-3). ``source``
is derived from ``context.profile`` by :func:`resolve_memory_write_source`, never
taken from the model-supplied tool params (RK-1); an optional ``evidence`` param
(verbatim customer phrase) is persisted alongside the write for audit, capped at
``MEMORY_EVIDENCE_MAX_LENGTH`` chars the same governed way. The slot enum, both
resolvers, and the value/evidence validators are all imported from the plugin so
the datastore and mock paths share one source of truth: this is security-sensitive
logic that must not drift between the two. The acting employee, when one exists,
is persisted in ``actor_account_id`` (0007 migration, nullable, no backfill) --
taken directly from ``context.user_id``, framework-set by the dispatch route from
the request's asserted actor and never model-supplied: present on a UI correction,
NULL on an AI draft-turn write or a provisional->verified merge (PRD 0.0.2 FR-4/R2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from toee_hermes.drivers.mock.memory import (
    MEMORY_PREFERENCE_SLOTS,
    _read_evidence,
    _require_value,
    resolve_customer_memory_binding,
    resolve_memory_write_source,
)
from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, new_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


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


def _upsert_preference(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    slot = _require_slot(params)
    value = _require_value(params)
    evidence = _read_evidence(params)
    # RK-1: source is framework-derived from context.profile (shared resolver, same
    # as the mock twin), never the model-supplied params — any "source" the caller
    # passed is ignored.
    source = resolve_memory_write_source(context)
    binding_key, binding_kind = resolve_customer_memory_binding(context, params)
    # FR-4/R2: actor is framework-derived from context.user_id -- the dispatch
    # route sets it from the request's asserted actor_account_id (ADR-0141), never
    # a model-supplied param. Present -> a UI correction; absent (None) -> an AI
    # draft-turn write, same presence check resolve_memory_write_source already
    # makes for source (PRD §9).
    actor_account_id = context.user_id
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_slot
                (id, binding_key, binding_kind, slot_name, slot_value, source,
                 evidence, actor_account_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (binding_key, slot_name) DO UPDATE SET
                slot_value = EXCLUDED.slot_value,
                source = EXCLUDED.source,
                evidence = EXCLUDED.evidence,
                binding_kind = EXCLUDED.binding_kind,
                actor_account_id = EXCLUDED.actor_account_id,
                updated_at = now(),
                last_interaction_at = now()
            """,
            (new_id("mem"), binding_key, binding_kind, slot, value, source, evidence,
             actor_account_id),
        )
    return {
        "binding_key": binding_key,
        "slot": slot,
        "value": value,
        "source": source,
        "evidence": evidence,
        "stored": True,
    }


def _clear_preference(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    slot = _require_slot(params)
    binding_key, _ = resolve_customer_memory_binding(context, params)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM customer_memory_slot WHERE binding_key = %s AND slot_name = %s",
            (binding_key, slot),
        )
    return {"binding_key": binding_key, "slot": slot, "cleared": True}


def _get_preferences(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    binding_key, _ = resolve_customer_memory_binding(context, params)
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


def _dismiss_proposal(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Audit-only write for a dismissed S14 proposal (0.0.3 S15, FR-16/FR-17).

    Persists no preference slot -- a bad guess can't quietly persist (US17) --
    only a Workbench Audit Log row recording the proposal (slot/value/evidence),
    the deciding employee, and the timestamp (``created_at``), mirroring the
    ``insert_audit`` calls the case handlers already make. Requires an
    attributed actor like every other governed employee decision (ADR-0141):
    a dismissal is always a rep at the keyboard, never the AI draft turn.
    """
    slot = _require_slot(params)
    value = _require_value(params)
    evidence = _read_evidence(params)
    account_id = context.user_id
    if not account_id:
        raise ToolDriverError(
            "policy_blocked",
            "A governed proposal dismissal requires an attributed actor.",
        )
    binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
    insert_audit(
        conn,
        profile=context.profile,
        account_id=account_id,
        action="proposal_dismissed",
        target_type="customer_memory_slot",
        target_id=slot,
        details={"slot": slot, "value": value, "evidence": evidence, "binding_key": binding_key},
    )
    return {"binding_key": binding_key, "slot": slot, "dismissed": True}


def memory_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the Customer Memory datastore tool."""
    return {
        "toee_customer_memory": {
            "upsert_preference": _upsert_preference,
            "clear_preference": _clear_preference,
            "get_preferences": _get_preferences,
            "dismiss_proposal": _dismiss_proposal,
        }
    }
