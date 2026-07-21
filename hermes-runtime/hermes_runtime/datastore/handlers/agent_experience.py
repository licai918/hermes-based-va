"""Postgres handler for ``toee_agent_experience`` (0.0.3 S22, FR-23/NFR-3).

L6 "what the agent learns from doing the job" -- mirrors the Customer Memory
governance skeleton (``handlers/memory.py``) for a NEW governed table in the
Toee Business Datastore, NOT Hermes's ``MEMORY.md``/state.db (ADR-0140
boundary). Proposals persist with ``status='proposed'`` directly: the
propose/confirm gate is status-based, so a proposed row is inert until an
admin flips it (S24) -- S25 is the only slice that ever reads/injects a
confirmed entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from toee_hermes.drivers.mock.agent_experience import (
    _context_strings,
    _read_proposer_context,
    _require_content,
    _require_id,
    _require_kind,
    resolve_agent_experience_source,
    resolve_experience_decision_authorization,
    scan_agent_experience_content,
)
from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, new_id, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


def _propose_experience(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    kind = _require_kind(params)
    content = _require_content(params)
    proposer_context = _read_proposer_context(params)
    # S22 write-side scan (the S09 hardening discipline floor): rejected
    # content never reaches the INSERT below.
    scan_agent_experience_content(content, *_context_strings(proposer_context))
    # RK-1 parity: source is framework-derived from context.profile, never the
    # model-supplied params -- any "source" the caller passed is ignored.
    source = resolve_agent_experience_source(context)
    entry_id = new_id("aexp")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_experience
                (id, kind, status, content, source, proposer_context)
            VALUES (%s, %s, 'proposed', %s, %s, %s)
            """,
            (entry_id, kind, content, source, Jsonb(proposer_context or {})),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="agent_experience_proposed",
        target_type="agent_experience",
        target_id=entry_id,
        details={"kind": kind, "source": source},
    )
    return {
        "id": entry_id,
        "kind": kind,
        "status": "proposed",
        "content": content,
        "source": source,
        "proposed": True,
    }


def _list_agent_experience(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Admin-only read of every ``agent_experience`` row (FR-23).

    Never registered as an LLM-callable tool (see ``_AGENT_EXCLUDED_ACTIONS``,
    the ``get_memory_audit`` precedent) -- reached only from the admin BFF's
    deterministic ``tools:dispatch`` call. S24 extends this into the
    Accept/Reject review queue; this slice is read-only.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, kind, status, content, source, proposer_context,
                   decider_account_id, decided_at, created_at, updated_at
            FROM agent_experience
            ORDER BY created_at DESC
            """
        )
        rows = cur.fetchall()
    return {"entries": [serialize_row(r) for r in rows]}


_ENTRY_COLUMNS = (
    "id, kind, status, content, source, proposer_context, "
    "decider_account_id, decided_at, created_at, updated_at"
)


def _decide_experience(
    conn,
    params: dict[str, Any],
    context: "ToolExecutionContext",
    *,
    new_status: str,
    audit_action: str,
) -> Any:
    """Shared UPDATE for confirm_experience/reject_experience (0.0.3 S24, FR-24).

    ONE code path for both governed decisions (only ``new_status``/
    ``audit_action`` differ), using the SAME ``resolve_experience_decision_
    authorization`` gate the mock twin calls, so the two can't drift on who is
    authorized to decide (the S15/S21 mock/Postgres lesson). The gate runs
    BEFORE the row lookup, so a missing actor is always ``policy_blocked``
    regardless of ``id``. The ``UPDATE ... WHERE status = 'proposed'``
    guard is the idempotency floor: only a still-proposed row transitions; a
    missing/already-decided row never corrupts state or re-decides -- a
    missing id is a governed ``not_found``, an already-decided id is a safe
    no-op that returns its current (unchanged) row.
    """
    entry_id = _require_id(params)
    decider = resolve_experience_decision_authorization(context)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            UPDATE agent_experience
            SET status = %s, decider_account_id = %s, decided_at = now(), updated_at = now()
            WHERE id = %s AND status = 'proposed'
            RETURNING {_ENTRY_COLUMNS}
            """,
            (new_status, decider, entry_id),
        )
        row = cur.fetchone()
    if row is None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {_ENTRY_COLUMNS} FROM agent_experience WHERE id = %s",
                (entry_id,),
            )
            existing = cur.fetchone()
        if existing is None:
            raise ToolDriverError(
                "not_found", f'agent_experience entry "{entry_id}" not found.'
            )
        # Already decided: safe no-op, no re-decide, no second audit row.
        return serialize_row(existing)
    insert_audit(
        conn,
        profile=context.profile,
        account_id=decider,
        action=audit_action,
        target_type="agent_experience",
        target_id=entry_id,
        details={"status": new_status},
    )
    return serialize_row(row)


def _confirm_experience(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    return _decide_experience(
        conn, params, context,
        new_status="confirmed", audit_action="agent_experience_confirmed",
    )


def _reject_experience(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    return _decide_experience(
        conn, params, context,
        new_status="rejected", audit_action="agent_experience_rejected",
    )


def agent_experience_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the L6 Agent-experience datastore tool."""
    return {
        "toee_agent_experience": {
            "propose_experience": _propose_experience,
            "list_agent_experience": _list_agent_experience,
            "confirm_experience": _confirm_experience,
            "reject_experience": _reject_experience,
        }
    }
