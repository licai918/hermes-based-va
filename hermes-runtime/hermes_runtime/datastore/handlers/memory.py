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

from psycopg.rows import dict_row

from toee_hermes.drivers.mock.memory import (
    _read_evidence,
    _require_slot,
    _require_value,
    is_verified_customer_identity,
    resolve_clear_authorization,
    resolve_customer_memory_binding,
    resolve_memory_write_source,
)
from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, new_id, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


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
    """Clears one preference slot and records an attributed audit row.

    0.0.3 S20 (FR-20): closes the 0.0.2 PAC-1 caveat -- a clear used to leave
    zero trace (a hard DELETE, no audit row). 0.0.3 S21 (FR-21, NFR-2) EXTENDS
    that same governed ``clear_preference`` action -- still the ONE write
    action, no new write path, no schema change -- to also authorize a
    VERIFIED customer clearing their OWN binding on the EXTERNAL profile.

    Who is authorized (rep/supervisor with an attributed actor, or a verified
    EXTERNAL customer) and the resulting audited ``account_id``/``initiator``
    are resolved by the shared ``resolve_clear_authorization`` -- the SAME
    resolver the mock driver's ``clear_preference`` calls, so this
    security-sensitive gate can't drift between the two twins (see its
    docstring for the full per-profile behavior).
    """
    slot = _require_slot(params)
    account_id, initiator = resolve_clear_authorization(context)

    binding_key, _ = resolve_customer_memory_binding(context, params)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM customer_memory_slot WHERE binding_key = %s AND slot_name = %s",
            (binding_key, slot),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=account_id,
        action="preference_cleared",
        target_type="customer_memory_slot",
        target_id=slot,
        details={"slot": slot, "binding_key": binding_key, "initiator": initiator},
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


def _get_my_memory_summary(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Customer-safe self-service summary read (0.0.3 S21, FR-21, NFR-2).

    Verified-only, same gate as the extended ``_clear_preference`` above: an
    EXTERNAL caller who is not a verified customer (unmatched, provisional, or
    ambiguous) gets ZERO data, never able to probe another customer's
    provisional slots by holding their phone/email (fail-closed, US13). Strips
    ALL internal metadata -- slot values only, no source, no actor, no
    timestamps, no binding_key -- reusing ``_get_preferences``' query but never
    its full response shape.

    NOTE: despite the "customer-facing" framing, ``get_my_memory_summary`` is
    also LLM-callable on internal_copilot (it isn't in
    ``_AGENT_EXCLUDED_ACTIONS``, so unexcluded actions ride the shared toolset
    registration onto INTERNAL's tool loop too). Not a gap: INTERNAL already
    has ``get_preferences``, a superset read.
    """
    if not is_verified_customer_identity(context.identity):
        raise ToolDriverError(
            "policy_blocked",
            "Customer Memory self-service requires a verified customer identity.",
        )
    binding_key, _ = resolve_customer_memory_binding(context, params)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_name, slot_value FROM customer_memory_slot WHERE binding_key = %s",
            (binding_key,),
        )
        rows = cur.fetchall()
    return {"preferences": {name: value for name, value in rows}}


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


def _get_memory_audit(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Supervisor Memory Audit View read (0.0.3 S20, FR-20).

    "Full write history" is the UNION of two sources, no schema change: (1) the
    current ``customer_memory_slot`` rows -- who wrote what's live now, with
    source/actor/evidence/timestamps; (2) the append-only ``workbench_audit_log``
    trail for this binding (``proposal_dismissed`` from S15, ``preference_cleared``
    from this slice, and any future merge-audit row that carries the same
    ``binding_key`` in its ``details`` -- S16 joins accepted proposals into the
    same view later, so this deliberately does not filter any action out).
    Read-only: no write, no schema change. Never registered as an LLM-callable
    tool (see ``_AGENT_EXCLUDED_ACTIONS``) -- reached only from the admin BFF's
    deterministic ``tools:dispatch`` call.
    """
    binding_key, _ = resolve_customer_memory_binding(context, params)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT slot_name, slot_value, source, actor_account_id, evidence,
                   created_at, updated_at
            FROM customer_memory_slot
            WHERE binding_key = %s
            ORDER BY slot_name
            """,
            (binding_key,),
        )
        slots = cur.fetchall()
        cur.execute(
            """
            SELECT a.*, acct.username AS actor_username
            FROM workbench_audit_log a
            LEFT JOIN workbench_account acct ON acct.id = a.account_id
            WHERE a.target_type = 'customer_memory_slot'
              AND a.details ->> 'binding_key' = %s
            ORDER BY a.created_at DESC
            """,
            (binding_key,),
        )
        audit_rows = cur.fetchall()
    return {
        "binding_key": binding_key,
        "slots": [serialize_row(r) for r in slots],
        "audit": [serialize_row(r) for r in audit_rows],
    }


def memory_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the Customer Memory datastore tool."""
    return {
        "toee_customer_memory": {
            "upsert_preference": _upsert_preference,
            "clear_preference": _clear_preference,
            "get_preferences": _get_preferences,
            "get_my_memory_summary": _get_my_memory_summary,
            "dismiss_proposal": _dismiss_proposal,
            "get_memory_audit": _get_memory_audit,
        }
    }
