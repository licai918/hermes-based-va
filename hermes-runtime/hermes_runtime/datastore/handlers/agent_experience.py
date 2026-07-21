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
    _require_kind,
    resolve_agent_experience_source,
    scan_agent_experience_content,
)

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


def agent_experience_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the L6 Agent-experience datastore tool."""
    return {
        "toee_agent_experience": {
            "propose_experience": _propose_experience,
            "list_agent_experience": _list_agent_experience,
        }
    }
