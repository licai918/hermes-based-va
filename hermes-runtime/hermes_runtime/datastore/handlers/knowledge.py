"""Datastore handlers for ``toee_knowledge_ops`` (ADR-0003/0087/0145).

The Supervisor Admin ``/admin/knowledge`` master-detail (ADR-0087) authors the six
Required Operational Policy Slots (ADR-0003) with a draft -> pending_eval ->
published lifecycle, separate draft/published text, owner/review metadata, and a
published-version history for rollback. ADR-0145 cuts this over from the in-memory
``KnowledgeStore`` (the behavioral source of truth) onto a dedicated
``workbench_policy_slot`` (+ ``workbench_policy_slot_history``) table that mirrors
its ``PolicySlot`` shape field-for-field. Writes are Supervisor governance: each is
fail-closed on an attributed actor and appends a Workbench Audit Log row.

``knowledge_version`` + :func:`publish_pending_slot` are the *separate* eval
publish-gate model (ADR-0040), left untouched here and shared with
``eval_review.promote_pending_policy`` (#44 territory). The authoring table and the
publish gate are intentionally decoupled in this increment (ADR-0145 divergence #2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from psycopg.rows import dict_row

from toee_hermes.errors import ToolDriverError
from toee_hermes.operational_policy import REQUIRED_POLICY_SLOTS

from ._common import insert_audit, read_string, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

# The wire-safe PolicySlot read model the BFF maps onto camelCase (ADR-0145).
_SLOT_COLUMNS = (
    "slot_id, title, status, draft_text, published_text, owner, review_date, has_gap_prompt"
)


def _require_actor(context: "ToolExecutionContext") -> str:
    """The acting Supervisor Admin for a governed knowledge write, or a denial.

    KnowledgeOps mutations are actor-attributed governance (ADR-0029/0087/0141):
    the actor rides ``ToolExecutionContext.user_id``, asserted by the BFF under the
    shared bearer. Trusting an absent actor would write the mutation *and* a
    NULL-actor audit row while returning success. Fail closed so every knowledge
    write handler is protected at once. (Mirrors ``accounts._require_actor``.)
    """
    actor = context.user_id
    if not actor:
        raise ToolDriverError(
            "policy_blocked", "A governed knowledge write requires an attributed actor."
        )
    return actor


def _optional_str(params: dict[str, Any], *keys: str) -> Optional[str]:
    """First *provided* string among ``keys`` (snake-first), keeping ``""``.

    Unlike ``read_string`` (which drops empty strings), this distinguishes an
    explicitly-provided empty string from an absent key, so ``saveDraft`` parity
    holds: sending ``draftText: ""`` clears the draft, while omitting it leaves the
    stored value untouched (``COALESCE(NULL, col)``).
    """
    for key in keys:
        value = params.get(key)
        if isinstance(value, str):
            return value
    return None


def _slot_row(conn, slot_id: str) -> Any:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_SLOT_COLUMNS} FROM workbench_policy_slot WHERE slot_id = %s",
            (slot_id,),
        )
        return serialize_row(cur.fetchone())


def _get_policy_slots(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    # listSlots() parity: every Required Operational Policy Slot, in the fixed
    # ADR-0003 list order (sort_order). A read -> no actor required, no audit.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_SLOT_COLUMNS} FROM workbench_policy_slot ORDER BY sort_order"
        )
        rows = cur.fetchall()
    return {"slots": [serialize_row(row) for row in rows]}


def _update_policy_slot(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    # saveDraft parity: patch only the provided fields and flip empty/gap -> draft
    # when the resulting draft text is non-empty, atomically in one UPDATE. An
    # unknown slot id is not_found (BFF -> 404), store-path parity.
    actor = _require_actor(context)
    slot_id = read_string(params, "slot_id", "slotId", "slot")
    if slot_id is None:
        raise ToolDriverError("unexpected_error", "slot_id is required.")
    fields = {
        "slot_id": slot_id,
        "draft_text": _optional_str(params, "draft_text", "draftText"),
        "owner": _optional_str(params, "owner"),
        "review_date": _optional_str(params, "review_date", "reviewDate"),
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            UPDATE workbench_policy_slot SET
                draft_text = COALESCE(%(draft_text)s, draft_text),
                owner = COALESCE(%(owner)s, owner),
                review_date = COALESCE(%(review_date)s, review_date),
                status = CASE
                    WHEN COALESCE(%(draft_text)s, draft_text) IS NOT NULL
                         AND length(COALESCE(%(draft_text)s, draft_text)) > 0
                         AND status IN ('empty', 'gap')
                    THEN 'draft'
                    ELSE status
                END,
                updated_at = now()
            WHERE slot_id = %(slot_id)s
            RETURNING {_SLOT_COLUMNS}
            """,
            fields,
        )
        row = cur.fetchone()
    if row is None:
        raise ToolDriverError("not_found", "slot not found")
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="update_policy_slot",
        target_type="policy_slot",
        target_id=slot_id,
        details={"status": row["status"]},
    )
    return {"slot": serialize_row(row)}


def _submit_for_eval(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    # submitForEval parity: requires a non-empty draft. The atomic UPDATE only
    # matches a slot that has one; rowcount 0 is disambiguated into not_found (404,
    # unknown slot) vs conflict (409, "slot has no draft to submit").
    actor = _require_actor(context)
    slot_id = read_string(params, "slot_id", "slotId", "slot")
    if slot_id is None:
        raise ToolDriverError("unexpected_error", "slot_id is required.")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            UPDATE workbench_policy_slot
            SET status = 'pending_eval', updated_at = now()
            WHERE slot_id = %s AND draft_text IS NOT NULL AND length(draft_text) > 0
            RETURNING {_SLOT_COLUMNS}
            """,
            (slot_id,),
        )
        row = cur.fetchone()
    if row is None:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM workbench_policy_slot WHERE slot_id = %s", (slot_id,))
            exists = cur.fetchone() is not None
        if not exists:
            raise ToolDriverError("not_found", "slot not found")
        raise ToolDriverError("conflict", "slot has no draft to submit")
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="submit_for_eval",
        target_type="policy_slot",
        target_id=slot_id,
        details={},
    )
    return {"slot": serialize_row(row)}


def _rollback_published_policy(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # rollbackPublished parity: restore the previous published text from history.
    # Unknown slot -> not_found (404); no prior version -> conflict (409). The pop
    # is a single DELETE ... RETURNING so two concurrent rollbacks can't both claim
    # the same history row.
    actor = _require_actor(context)
    slot_id = read_string(params, "slot_id", "slotId", "slot")
    if slot_id is None:
        raise ToolDriverError("unexpected_error", "slot_id is required.")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM workbench_policy_slot WHERE slot_id = %s", (slot_id,))
        if cur.fetchone() is None:
            raise ToolDriverError("not_found", "slot not found")
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM workbench_policy_slot_history
            WHERE id = (
                SELECT id FROM workbench_policy_slot_history
                WHERE slot_id = %s
                ORDER BY archived_at DESC, id DESC
                LIMIT 1
            )
            RETURNING published_text
            """,
            (slot_id,),
        )
        popped = cur.fetchone()
    if popped is None:
        raise ToolDriverError("conflict", "slot has no previous published version")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workbench_policy_slot"
            " SET published_text = %s, status = 'published', updated_at = now()"
            " WHERE slot_id = %s",
            (popped[0], slot_id),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="rollback_published_policy",
        target_type="policy_slot",
        target_id=slot_id,
        details={},
    )
    return {"slot": _slot_row(conn, slot_id)}


# --- Eval publish-gate (ADR-0040) — separate model, left untouched (#44) --------
# knowledge_version + publish_pending_slot are the eval publish-gate, shared with
# eval_review.promote_pending_policy. They are NOT the authoring path above and are
# intentionally decoupled from workbench_policy_slot in this increment (ADR-0145).


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


def publish_pending_slot(conn, slot: Optional[str]) -> int:
    """Promote a slot's latest ``pending_eval`` version to ``published``.

    Shared with ``eval_review.promote_pending_policy`` (ADR-0040: publish is gated
    by the eval review). Operates on ``knowledge_version``, the eval publish-gate
    model — separate from the ``workbench_policy_slot`` authoring table (ADR-0145).
    Returns the promoted version.
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
