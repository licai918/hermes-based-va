"""Datastore handlers for ``toee_knowledge_ops`` (ADR-0003/0040/0087).

Operational Policy Knowledge is versioned per slot in ``knowledge_version`` with a
draft -> pending_eval -> published lifecycle (publish is gated by the eval review,
ADR-0040, and lives in ``eval_review``). The six Required Operational Policy Slots
(ADR-0003) always exist; ``get_policy_slots`` overlays stored versions onto the
canonical placeholders. Mutations are Supervisor governance and write audit rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from psycopg.rows import dict_row

from toee_hermes.errors import ToolDriverError
from toee_hermes.operational_policy import (
    REQUIRED_POLICY_SLOTS,
    SLOT_STATUS_EMPTY,
    SLOT_TITLES,
)

from ._common import insert_audit, new_id, read_string

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


def _require_known_slot(slot: Optional[str]) -> str:
    if slot is None:
        raise ToolDriverError("unexpected_error", "slot is required.")
    if slot not in REQUIRED_POLICY_SLOTS:
        raise ToolDriverError("unexpected_error", f'Unknown policy slot "{slot}" (ADR-0003).')
    return slot


def _latest_version(conn, slot: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM knowledge_version WHERE slot_key = %s ORDER BY version DESC LIMIT 1",
            (slot,),
        )
        return cur.fetchone()


def _next_version(conn, slot: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM knowledge_version WHERE slot_key = %s",
            (slot,),
        )
        return cur.fetchone()[0]


def _get_policy_slots(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    latest: dict[str, dict[str, Any]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (slot_key)
                slot_key, content, status, version, published_at
            FROM knowledge_version
            ORDER BY slot_key, version DESC
            """
        )
        for row in cur.fetchall():
            latest[row["slot_key"]] = row
    slots = []
    for key in REQUIRED_POLICY_SLOTS:
        entry: dict[str, Any] = {
            "key": key,
            "title": SLOT_TITLES[key],
            "status": SLOT_STATUS_EMPTY,
            "owner": None,
            "review_date": None,
            "content": "",
        }
        row = latest.get(key)
        if row is not None:
            entry["status"] = row["status"]
            entry["content"] = row["content"]
            entry["version"] = row["version"]
            published_at = row["published_at"]
            if published_at is not None:
                entry["published_at"] = published_at.isoformat()
        slots.append(entry)
    return {"slots": slots}


def _update_policy_slot(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    slot = _require_known_slot(read_string(params, "slot"))
    content = read_string(params, "content") or ""
    version = _next_version(conn, slot)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO knowledge_version (id, slot_key, content, status, version)
            VALUES (%s, %s, %s, 'draft', %s)
            """,
            (new_id("kv"), slot, content, version),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="update_policy_slot",
        target_type="policy_slot",
        target_id=slot,
        details={"version": version},
    )
    return {"slot": slot, "state": "draft", "version": version, "updated": True}


def _submit_for_eval(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    slot = _require_known_slot(read_string(params, "slot"))
    latest = _latest_version(conn, slot)
    if latest is None or latest["status"] != "draft":
        raise ToolDriverError("unexpected_error", f"no draft to submit for slot {slot}.")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE knowledge_version SET status = 'pending_eval' WHERE id = %s",
            (latest["id"],),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="submit_for_eval",
        target_type="policy_slot",
        target_id=slot,
        details={"version": latest["version"]},
    )
    return {"slot": slot, "submitted": True, "status": "pending_eval"}


def _rollback_published_policy(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    slot = _require_known_slot(read_string(params, "slot"))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM knowledge_version
            WHERE slot_key = %s AND status = 'published'
            ORDER BY version DESC LIMIT 1
            """,
            (slot,),
        )
        published = cur.fetchone()
    if published is None:
        raise ToolDriverError(
            "unexpected_error", f"no published policy to roll back for slot {slot}."
        )
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE knowledge_version SET status = 'rolled_back' WHERE id = %s",
            (published["id"],),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="rollback_published_policy",
        target_type="policy_slot",
        target_id=slot,
        details={"version": published["version"]},
    )
    return {"slot": slot, "rolled_back": True}


def publish_pending_slot(conn, slot: Optional[str]) -> int:
    """Promote a slot's latest ``pending_eval`` version to ``published``.

    Shared with ``eval_review.promote_pending_policy`` (ADR-0040: publish is
    gated by the eval review). Returns the promoted version.
    """
    resolved = _require_known_slot(slot)
    latest = _latest_version(conn, resolved)
    if latest is None or latest["status"] != "pending_eval":
        raise ToolDriverError(
            "unexpected_error", f"no pending_eval policy to promote for slot {resolved}."
        )
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE knowledge_version SET status = 'published', published_at = now() WHERE id = %s",
            (latest["id"],),
        )
    return latest["version"]


def knowledge_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the knowledge-ops datastore tool."""
    return {
        "toee_knowledge_ops": {
            "get_policy_slots": _get_policy_slots,
            "update_policy_slot": _update_policy_slot,
            "submit_for_eval": _submit_for_eval,
            "rollback_published_policy": _rollback_published_policy,
        }
    }
